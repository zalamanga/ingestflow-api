# Membuat IngestFlow dari nol

Panduan ini mengikuti kode yang ada di repository. Tujuannya memahami mengapa API mengembalikan job ID lebih dulu, bagaimana worker bekerja, dan bagaimana transaksi menjaga perubahan data. Data contoh adalah barang sintetis, tanpa akun pelanggan atau integrasi layanan luar.

## 1. Mulai dari kontrak

Klien mengirim `POST /v1/imports`, header bearer tenant, `Idempotency-Key`, dan body CSV. API menyimpan job ke PostgreSQL lalu mengembalikan `202`. Proses worker yang berbeda mengambil job, memvalidasi semua baris, lalu menerapkan perubahan. Klien membaca status melalui `GET /v1/imports/{id}`.

Contoh masalah yang diselesaikan: jaringan putus setelah server menerima file. Klien tidak tahu apakah impor sudah dibuat. Jika langsung membuat permintaan baru dengan ID baru, file bisa diimpor dua kali. IngestFlow memakai kunci idempotensi yang sama agar klien bisa meminta hasil penerimaan sebelumnya.

## 2. `requirements.txt` dan `requirements-dev.txt`

`fastapi` mendefinisikan route HTTP dan schema OpenAPI. `uvicorn` menjalankan aplikasi ASGI. `psycopg` adalah driver PostgreSQL; `psycopg-binary` menyediakan komponen binernya. Pydantic memvalidasi parameter dan model response. File requirements runtime mematok versi dependensi agar perubahan package tidak terjadi diam-diam.

File dev menambah pytest untuk pengujian dan HTTPX untuk TestClient. PostgreSQL tetap database asli saat test, bukan tiruan dictionary. Test-only package tidak ikut dipasang ulang dalam target Docker runtime.

## 3. `ingestflow/config.py`

`Settings` adalah dataclass dengan `frozen=True`. Setelah dibuat, kode tidak bisa mengganti nilai field secara biasa. Isinya URL database, dua digest kunci tenant, nama schema dan durasi lease.

`__post_init__()` menolak konfigurasi kosong, digest yang bukan 64 hex, dua tenant yang memakai digest sama, schema yang tidak diizinkan, dan lease di luar batas. Error konfigurasi muncul saat startup, sehingga server tidak berjalan dengan autentikasi kosong.

`from_env()` membaca process environment. Nilai raw tenant key tidak dibutuhkan oleh aplikasi. Nama schema default `public`; test hanya boleh memakai pola `test_<32 hex>`.

## 4. `migrations/001_init.sql`

Tabel `tenants` memuat dua identitas demo: `alpha` dan `beta`. Tabel ini juga menjadi titik row lock untuk pemeriksaan kapasitas dan idempotensi per tenant.

`imports` menyimpan ID UUID, sequence untuk pagination, tenant, kunci idempotensi, hash permintaan, CSV `bytea`, status, jumlah claim, token lease, waktu lease, counter hasil dan laporan error. Unique constraint `(tenant_id,idempotency_key)` mencegah dua job untuk satu kunci tenant. `CHECK` membatasi ukuran payload dan jumlah percobaan.

`records` menyimpan hasil impor. Primary key `(tenant_id,sku)` berarti SKU yang sama pada tenant berbeda tidak saling menimpa. Foreign key gabungan `(tenant_id,source_import_id)` mencegah record mengarah ke job tenant lain. Collation `C` memberi urutan SKU ASCII untuk cursor yang konsisten.

`import_events` menyimpan perubahan lifecycle. Detail event hanya berisi hitungan atau kode, tanpa isi CSV. Index queue dan expired membantu worker memilih baris tanpa membaca semua payload.

## 5. `ingestflow/db.py`

`connect()` adalah context manager. `with connect(settings) as conn:` membuka koneksi dengan batas waktu, lalu commit jika blok berhasil. Jika ada exception, transaksi di-rollback oleh context psycopg. `dict_row` membuat hasil query bisa dibaca sebagai `row['status']`.

`migrate()` membaca SQL, menghitung SHA-256, dan mengambil advisory transaction lock. Jika migration sudah diterapkan dengan checksum yang sama, fungsi selesai. Jika file migration lama diubah, fungsi menolak. Jika belum diterapkan, SQL dan catatan migration ditulis dalam satu transaksi.

Kenapa tidak membuat tabel di setiap handler? Migration adalah pekerjaan startup sekali jalan. Handler cukup bekerja dengan schema yang sudah siap.

## 6. `ingestflow/validation.py`

`Product` menyimpan kandidat `sku`, `name`, dan `quantity` yang sudah valid. `Validation` menyimpan kandidat, daftar error, jumlah error dan jumlah record yang diperiksa. Keduanya dataclass agar struktur hasil fungsi jelas.

`validate_csv(payload)` menerima `bytes`. Fungsi memeriksa ukuran, decode UTF-8, menolak null byte, lalu memakai `csv.reader(..., strict=True)`. Parser CSV diperlukan karena `split(',')` akan merusak nama barang yang berisi koma dan dikutip.

Header wajib tepat `sku,name,quantity`. Set `seen` mendeteksi SKU berulang di dalam satu file. Regex SKU hanya menerima huruf besar ASCII, angka, underscore dan hyphen. Quantity harus bilangan kanonis 0..999999, sehingga `01`, `-1`, `1.5` dan `NaN` ditolak.

Fungsi lokal `reject()` menambah jumlah error, tetapi hanya menyimpan 50 detail. Dengan cara ini respons tidak membesar mengikuti setiap kesalahan. Jika ada satu error pun, `rows` hasil akhir dikosongkan. Worker tidak akan menerapkan hanya bagian yang valid.

Nomor row adalah indeks record CSV logis, bukan selalu nomor baris fisik file. Sebuah quoted field bisa memuat newline, walaupun field nama yang berisi control character akhirnya ditolak.

## 7. `ingestflow/errors.py` dan `models.py`

`APIError` membawa HTTP status, kode stabil dan pesan aman. Kode handler melempar error domain ini tanpa menyisipkan SQL atau kredensial ke pesan.

Model `Job`, `JobPage`, `RecordPage`, `ErrorReport` dan `EventPage` menjelaskan bentuk response. FastAPI memakai model yang sama untuk validasi output dan OpenAPI. ID ditampilkan sebagai UUID, timestamp sebagai waktu, dan status memiliki pilihan yang terbatas.

## 8. `ingestflow/store.py`: penerimaan dan pembacaan

`job_view()` memilih field yang boleh keluar. Payload CSV, token lease dan kunci idempotensi tidak ikut dikirim. `event()` menambah lifecycle event dengan parameter query, bukan string SQL yang ditempel dari input pengguna.

`submit()` menghitung hash `tenant + NUL + raw CSV`, lalu mengunci baris tenant. Pertama, ia mencari kunci yang sudah ada. Hash sama mengembalikan job lama dengan penanda replay. Hash berbeda melempar `409`. Setelah itu fungsi memeriksa batas 200 retained job dan 50 active job, lalu membuat job dan event `QUEUED` dalam satu transaksi.

Row lock tenant membuat dua permintaan bersamaan memeriksa kunci dan kapasitas secara berurutan. Unique constraint tetap menjadi perlindungan database jika kode berubah pada masa depan. Row lock ini singkat; proses validasi CSV tidak dilakukan di dalam transaksi penerimaan.

`get_job()` selalu memfilter tenant dan ID. `list_jobs()` memakai `seq > after ORDER BY seq`, mengambil `limit + 1` agar tahu masih ada halaman berikutnya. `list_records()` memakai teknik yang sama dengan SKU. Pagination ini tidak membuat snapshot lintas beberapa HTTP request.

`error_report()` mengembalikan kode error dan indikator `truncated`, bukan nilai field asli. `list_events()` memeriksa kepemilikan job lalu membaca event tenant yang sama. `cancel()` mengambil row lock job sebelum mengubah status agar bersaing dengan transaksi apply worker di titik yang sama.

## 9. `ingestflow/worker.py`: claim

`claim()` mencari job `RUNNING` yang lease-nya lewat. `FOR UPDATE SKIP LOCKED` berarti worker mengunci baris yang diambil, tetapi melewati baris yang sedang dikunci proses lain. Worker tidak harus antre pada satu baris yang sibuk jika ada pekerjaan lain.

Jika jumlah claim masih di bawah tiga, job dikembalikan ke `QUEUED`. Jika sudah tiga, job menjadi `FAILED` dengan `lease_attempts_exhausted`. Setiap recovery memiliki event `LEASE_EXPIRED`.

Berikutnya worker memilih job queued dengan sequence paling awal yang tersedia. Ia membuat UUID token, menambah attempts, menyimpan deadline, dan menambah event `CLAIMED`. Fungsi baru mengembalikan payload setelah transaksi ini commit. Worker yang tiba-tiba mati sesudahnya meninggalkan status yang bisa dipulihkan.

## 10. `worker.py`: validasi dan apply

`run_once()` memanggil `claim()`, memvalidasi seluruh CSV di luar transaksi lock, lalu memanggil `complete()`. Opsi CLI `--once` melakukan satu putaran ini dan keluar. Mode biasa mengulang dengan jeda satu detik saat tidak ada pekerjaan.

`complete()` mengambil job `FOR UPDATE`, memeriksa status dan token, lalu mengecek deadline dengan jam database setelah lock didapat. Token lama, job yang dibatalkan dan lease yang habis tidak boleh mempublikasikan hasil.

Jika CSV invalid, fungsi menyimpan status `FAILED`, error dan event. Jika valid, kandidat diurutkan menurut SKU. Setiap record memakai `INSERT ... ON CONFLICT ... DO UPDATE`. Status `SUCCEEDED` dan event sukses berada dalam transaksi yang sama dengan semua upsert.

Jika upsert kedua gagal, upsert pertama juga di-rollback. Ini alasan penyimpanan status sukses tidak boleh dilakukan sebelum transaksi record selesai. Test failpoint mengangkat exception setelah write pertama untuk membuktikannya.

Lease memberi kesempatan worker lain mengambil pekerjaan setelah proses mati. Lease bukan janji bahwa fungsi hanya dipanggil sekali. Jaminan yang diberikan adalah token fencing dan atomicity PostgreSQL. Tidak ada heartbeat, message broker atau transaksi antar layanan.

## 11. `ingestflow/api.py`

`create_app(settings)` membuat FastAPI tanpa langsung membuka database. Ini memudahkan test memakai schema dan konfigurasi masing-masing.

Dependency `tenant()` membaca HTTP bearer, menghitung hash dan membandingkan digest dengan `hmac.compare_digest`. Handler menerima tenant dari dependency tersebut, bukan dari field body yang bisa dipalsukan.

`submit_import()` adalah `async def` karena membaca stream HTTP. Ia memeriksa content type, encoding, kunci dan batas byte ketika chunk datang. `asyncio.timeout(10)` membatasi waktu pembacaan. Operasi database sinkron dikirim melalui `run_in_threadpool` agar tidak menahan event loop saat menunggu PostgreSQL.

Handler baca lainnya memakai `def` biasa. FastAPI menjalankan handler sinkron di threadpool. Dengan begitu driver psycopg sinkron bisa dipakai tanpa memblokir event loop utama.

Exception handler `domain_error()` memberi format error stabil. `invalid_request()` tidak mengembalikan input rahasia yang ditangkap Pydantic. `database_error()` memberi `503` dan petunjuk replay dengan kunci lama. Middleware memasang `no-store`, `nosniff` dan kebijakan referrer.

OpenAPI berasal dari route dan response model. Body CSV ditulis dalam `openapi_extra` supaya Swagger menunjukkan `text/csv`, bukan mengira upload adalah JSON. `ingestflow/main.py` adalah entrypoint Uvicorn yang membangun app dari environment.

## 12. Docker dan Compose

`Dockerfile` memiliki target `base`, `runtime` dan `test`. Base memasang package pinned. Runtime hanya menyalin aplikasi dan migration, lalu memakai user nonroot 10001. Target test menambah pytest, HTTPX, test dan probe internal.

`compose.yml` memisahkan PostgreSQL, migration, API dan worker. API/worker memakai image yang sama dengan command berbeda. Migration harus selesai sebelum keduanya berjalan. Volume PostgreSQL mempertahankan data saat container dihentikan. API/worker memakai filesystem read-only dan tmpfs terbatas.

`compose.test.yml` memakai database `ingestflow_test` yang berbeda dan tmpfs. File ini tidak menumpang data aplikasi. Semua port yang diekspos hanya bind ke `127.0.0.1`.

## 13. Script pengoperasian

`scripts/init_env.py` membuat kunci random melalui `secrets.token_hex(32)`, menghitung digest, dan menyimpan dua file privat yang diabaikan Git. Nilainya tidak dicetak.

`Common.ps1` menjalankan command native dengan pemeriksaan exit code dan membatasi TEMP/cache ke `.local` pada folder proyek. `Init.ps1`, `Start.ps1`, `Stop.ps1` dan `Test.ps1` memakai helper itu. Blok `finally` mengembalikan process environment walaupun command gagal.

`scripts/smoke.py` benar-benar memanggil HTTP API yang sedang berjalan. Ia menunggu worker terpisah menulis record. `scripts/export_openapi.py` menghasilkan snapshot kontrak dari kode route, bukan menulis ulang API secara manual.

## 14. Baca test agar memahami jaminan

`tests/test_validation.py` menguji parser dan batas input. `tests/conftest.py` memaksa nama database test yang aman, membuat schema unik, menerapkan migration dan membersihkannya setelah test.

`tests/test_contract.py` memeriksa OpenAPI, kebutuhan header, penolakan body tanpa mengakses database, serta respons `503` yang tidak membocorkan connection string. Snapshot OpenAPI dibandingkan dengan route nyata agar dokumentasi tidak tertinggal.

`tests/test_postgres.py` menguji enam permintaan penerimaan bersamaan, dua worker claim bersamaan, tenant isolation, cancellation race, expired-token fencing, cap tiga attempts dan rollback. Tidak ada SQLite pengganti untuk menguji lock PostgreSQL.

`tests/claim_and_pause.py` hanya helper test. Ia mengklaim job, menulis marker setelah commit, lalu menunggu. Test parent menunggu marker, membunuh subprocess, menunggu deadline sungguhan habis, lalu memproses recovery. Helper ini tidak mempunyai route HTTP dan tidak disalin ke image runtime.

`.github/workflows/verify.yml` mengulangi pengujian pada runner Linux, tempat `child.kill()` benar-benar mengirim SIGKILL. Workflow juga menjalankan probe HTTP dan memeriksa snapshot OpenAPI. Hasil eksekusi harus diperiksa di CI atau catatan verifikasi; jumlah test yang ditulis bukan bukti test sudah lulus.
