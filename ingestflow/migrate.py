from .config import Settings
from .db import migrate

if __name__ == "__main__":
    migrate(Settings.from_env())
    print("Migration complete")
