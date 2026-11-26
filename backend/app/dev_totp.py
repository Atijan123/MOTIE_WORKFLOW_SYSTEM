"""Print the current sign-in code for the seeded dev staff accounts (step 12e).

    docker compose run --rm tools python -m app.dev_totp

The same 6 digits an authenticator app set up with dev_seed.DEV_TOTP_SECRET
shows right now. Development only: it refuses to run otherwise.
"""

import sys
import time

from app.core.config import settings
from app.core.identity import totp
from app.dev_seed import DEV_TOTP_SECRET


def main() -> None:
    if settings.app_env != "development":
        sys.exit(f"Refusing: APP_ENV is '{settings.app_env}', not 'development'.")
    left = totp.PERIOD - int(time.time()) % totp.PERIOD
    print(f"{totp.code_at(DEV_TOTP_SECRET, totp.current_step())}  (good for {left} more seconds, and the 30 after)")


if __name__ == "__main__":
    main()
