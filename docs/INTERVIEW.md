# Interview walkthrough

## Penjelasan satu menit

Saya membuat REST API untuk impor CSV inventory yang diproses worker terpisah. API menyimpan job dan bytes ke PostgreSQL, lalu mengembalikan `202`. Klien memakai idempotency key agar retry setelah jaringan putus tidak membuat job baru. Worker mengklaim dengan row lock dan lease token. Semua baris divalidasi sebelum produk ditulis. Jika ada satu baris invalid, seluruh impor gagal tanpa perubahan produk.

Bagian yang saya ingin tunjukkan adalah transaksi, konkurensi dan recovery. Produk, status sukses dan audit event berada dalam satu transaksi. Worker yang mati setelah claim bisa dipulihkan setelah lease lewat. Tenant lain tidak bisa melihat job lewat ID yang diketahui. Test menggunakan PostgreSQL asli dan subprocess worker yang benar-benar dibunuh.

## Urutan demo

1. Jalankan `Start.ps1`, buka `/docs`, dan authorize memakai kunci alpha privat.
2. Kirim `examples/valid.csv` melalui Postman atau curl dengan key baru. Catat `202`, ID dan `Location`.
3. Kirim byte yang sama memakai key yang sama. ID harus tetap sama. Tambahkan satu newline dengan key yang sama, hasilnya `409`.
4. Baca job dan `/v1/records` untuk melihat hasil worker terpisah.
5. Kirim `examples/invalid.csv` dengan key baru. Tunjukkan status gagal dan `/errors`; baris valid dalam file itu juga tidak diterapkan.
6. Ganti authorize ke beta, baca ID alpha yang tadi. API mengembalikan `404`.
7. Tunjukkan test race, rollback dan subprocess-kill di `tests/test_postgres.py`, beserta hasil eksekusi yang benar-benar ada.

Jangan tampilkan file `.env`, password database, atau dialog authorize berisi kunci pada rekaman publik.

## Pertanyaan teknis

**Mengapa worker terpisah?** Proses HTTP tidak perlu menunggu validasi dan seluruh write selesai. Job tetap ada bila API restart karena input sudah disimpan dalam database, bukan background task dalam memory API.

**Apakah worker bisa memproses ulang job?** Bisa setelah claim sebelumnya expired. Token fencing memblokir worker lama. Apply bersifat atomic di PostgreSQL. Saya tidak menyebut sistem ini distributed exactly-once karena tidak ada transaksi global antar layanan.

**Apa yang terjadi jika server commit tetapi respons hilang?** Klien replay kunci dan byte yang sama, sehingga menemukan job yang sudah tersimpan. Menggunakan kunci baru saat hasil sebelumnya tidak pasti justru menghilangkan manfaat idempotensi.

**Mengapa tenant row lock?** Penerimaan job perlu memeriksa kunci dan kapasitas tenant secara konsisten saat request bersamaan. Lock hanya dipakai untuk transaksi penerimaan, bukan selama parsing seluruh file.

**Bagaimana cancel berlomba dengan worker?** Keduanya mengunci row job yang sama. Cancel yang commit lebih dulu mengganti status dan menghapus lease token. Apply yang sudah menang lock akan commit; cancel setelahnya mendapat `409`.

**Mengapa SKU diurutkan sebelum upsert?** Dua job yang menulis beberapa SKU overlapping memperoleh lock record dalam urutan yang sama. Ini mengurangi risiko deadlock. PostgreSQL tetap menjadi penentu commit order, bukan urutan submit aplikasi.

**Apa kekurangan desain saat ini?** Dua tenant memakai demo key tetap, belum ada user management atau key rotation. CSV kecil, kapasitas job dibatasi dan tidak ada endpoint purge. Tidak ada heartbeat, broker, cross-request snapshot, SLA atau hosting publik. Batas ini ditulis agar reviewer tahu jangkauan implementasinya.

**Apa pengembangan berikutnya jika dipakai tim?** Mulai dari kebutuhan nyata: identitas pengguna dan scoped keys, kebijakan retensi, pengukuran durasi worker untuk memilih lease, observability tanpa payload, TLS dan backup. Hindari menambah broker sebelum antrean PostgreSQL yang ada terbukti menjadi batas.
