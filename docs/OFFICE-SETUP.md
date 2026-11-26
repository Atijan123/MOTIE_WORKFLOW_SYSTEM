# Setting up the office server

This guide sets up the ETLS system on one computer in the Ministry's office,
on the office network only, with real data. Follow it in order. Commands you
type are in grey boxes; **▶** marks the ones to run. Most need `sudo` (an
administrator): you'll be asked for your Ubuntu password.

What you'll end up with:

```
 Staff PCs and phones ──(office Wi-Fi / LAN, https)──▶ the server
                                                        ├─ Caddy (https, the only door)
                                                        ├─ the staff app
                                                        ├─ the API
                                                        ├─ Postgres (the database)
                                                        └─ nightly backup ──▶ USB drive
 Nothing is reachable from the internet. There is no applicant portal:
 Records enters every application (office mode, APP_ENV=office).
```

Contents:
1. What you need
2. Install Ubuntu
3. A fixed address, a name, and the firewall
4. Automatic security updates
5. Install Docker
6. Get the system and fill in its settings
7. The backup drive and the off-site key
8. The first start
9. Trust the server's certificate (every PC and phone)
10. Staff accounts and two-step sign-in
11. Import the historical register
12. The UPS: shutting down cleanly on a power cut
13. Daily, weekly and monthly checks
14. Updates
15. If the server dies: rebuilding from a backup
16. Phones on the office Wi-Fi

---

## 1. What you need

- **A computer to be the server**: any recent PC with 8 GB of memory or more,
  an SSD of 256 GB or more, and a network cable to the office router. It will
  run all the time.
- **A UPS** (uninterruptible power supply) with a **USB cable** to the server,
  e.g. an APC Back-UPS or an Eaton 5E. Power cuts are frequent; see section 12.
- **Two USB backup drives** (1 TB is plenty): one stays plugged into the
  server, one goes off-site; you swap them weekly (section 13).
- **Two small USB sticks** for the keys (section 7), kept in two different
  safe places.
- The **router's admin password** (to give the server a fixed address and a
  name), and the **office network's address range** (e.g. `192.168.10.0/24`).
- A USB stick of 8 GB or more to install Ubuntu from.

## 2. Install Ubuntu

1. On another PC, download **Ubuntu Server 24.04 LTS** from
   https://ubuntu.com/download/server and write it to the 8 GB stick with
   balenaEtcher (https://etcher.balena.io).
2. Boot the server from the stick (usually F12 or F2 at start-up) and install:
   - language English, keyboard as yours;
   - network: leave it on automatic for now (section 3 fixes the address);
   - storage: "Use an entire disk", and **tick "Set up this disk as an LVM
     group"** (the default);
   - your name, the server's name (e.g. `motie-server`), a user name (e.g.
     `motieadmin`) and a **long password**, kept in the safe;
   - **tick "Install OpenSSH server"** (so ICT can work on it from their PC);
   - no extra snaps.
3. Reboot, remove the stick, and sign in.

**▶** Bring everything up to date:
```bash
sudo apt update && sudo apt full-upgrade -y && sudo reboot
```

## 3. A fixed address, a name, and the firewall

**A fixed address.** In the router's admin page, find "DHCP reservation" (or
"Static lease") and give the server a fixed address, e.g. `192.168.10.5`.
This is `OFFICE_BIND_IP` later. Restart the server and check it got it:

**▶**
```bash
ip -4 addr show | grep inet
```

**A name.** Staff will type a name, e.g. `etls.office`, not the number. In the
router, find "Local DNS" / "Host names" / "DNS records" and add
`etls.office → 192.168.10.5`. If the router can't, add the same line to each
PC's hosts file (`C:\Windows\System32\drivers\etc\hosts`); phones then need
the router's DNS, so prefer the router.

**No port forwarding.** In the router, check that **no port forwarding**
points at the server. This is what keeps it off the internet.

**The firewall** allows only the office network in, and only https, http
(which just redirects to https) and SSH. **▶** Replace `192.168.10.0/24` with
your office range:
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.10.0/24 to any port 22 proto tcp
sudo ufw allow from 192.168.10.0/24 to any port 443 proto tcp
sudo ufw allow from 192.168.10.0/24 to any port 80 proto tcp
sudo ufw enable
sudo ufw status verbose
```

Docker opens its own ports past ufw. That's why the system also listens
**only on the office address** (`OFFICE_BIND_IP`), and the staff app checks
every request comes from `OFFICE_NETWORK`: three locks, not one.

## 4. Automatic security updates

Ubuntu can install security fixes by itself every night. **▶**
```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades     # answer "Yes"
```
Some fixes need a restart. Let it restart at 03:30, when nobody works and the
02:00 backup is done. **▶**
```bash
sudo nano /etc/apt/apt.conf.d/50unattended-upgrades
```
find these two lines, remove the `//` in front, and set them to:
```
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:30";
```
Save (Ctrl+O, Enter) and close (Ctrl+X). After a restart, the system starts
by itself (Docker's `restart: unless-stopped`).

## 5. Install Docker

From Docker's own repository (Ubuntu's own package is older). **▶**
```bash
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo docker run --rm hello-world
```
The last line should print "Hello from Docker!".

## 6. Get the system and fill in its settings

**▶** The code goes in `/opt/motie`:
```bash
sudo git clone https://github.com/Atijan123/MOTIE_WORKFLOW_SYSTEM.git /opt/motie
cd /opt/motie
```
(The repository is private: GitHub asks for a user name and a *token*. With no
internet, copy a bundle from a USB stick instead: section 14, "Offline".)

**▶** The settings: start from the template, then make each secret.
```bash
sudo cp office/env.example .env
sudo chmod 600 .env            # only an administrator may read it
openssl rand -hex 32           # run once per secret, and paste each into .env
sudo nano .env
```
Fill in **every** line; office/env.example explains each. Use a **different**
`openssl rand -hex 32` for each of `POSTGRES_PASSWORD`, `MIGRATION_DB_PASSWORD`,
`APP_DB_PASSWORD`, `JWT_SECRET`, `MFA_SECRET_KEY` and `STAFF_PORTAL_KEY`.
`OFFICE_NETWORK` is the range you'll be given (`[CONFIRM]`).
`FACILITY_LETTER_REFERENCE_FORMAT` comes from the Registry; signing is blocked
until it's set.

**Keep a copy of `.env` in the safe** (on one of the key sticks, section 7).
Without it, a restored backup can't be used: `MFA_SECRET_KEY` unlocks the
staff's two-step sign-in, and the database passwords are in it.

## 7. The backup drive and the off-site key

**The backup drive.** Plug in the first USB drive and find its name: **▶**
```bash
lsblk -o NAME,SIZE,MODEL
```
Say it's `sdb` (check the size!). **This erases the drive.** **▶**
```bash
sudo mkfs.ext4 -L MOTIEBACKUP /dev/sdb1     # if it has no partition: sudo mkfs.ext4 -L MOTIEBACKUP /dev/sdb
sudo mkdir -p /mnt/motie-backup
echo 'LABEL=MOTIEBACKUP /mnt/motie-backup ext4 defaults,nofail,x-systemd.device-timeout=10 0 2' | sudo tee -a /etc/fstab
sudo mount -a
sudo touch /mnt/motie-backup/.motie-backup-drive
```
`nofail` lets the server start without the drive. The `.motie-backup-drive`
file tells the backup "this is the real drive": without it, the backup
refuses to run rather than fill the server's own disk. **Prepare the second
drive the same way** (same label, same `touch`).

**The off-site key.** The weekly copy for off-site is encrypted. The server
keeps only the **public** half of the key, so a stolen server or drive can't
read it. **▶** Make the key pair (once):
```bash
cd /opt/motie
sudo docker compose build backup
sudo docker compose run --rm --entrypoint age-keygen backup | sudo tee /root/offsite.key
sudo grep -o 'age1[0-9a-z]*' /root/offsite.key | sudo tee office/keys/offsite.pub
```
Now copy `/root/offsite.key` (the **private** key) and `.env` to **both** key
sticks, then delete the private key from the server: **▶**
```bash
sudo cp /root/offsite.key .env /media/<the key stick>/      # once per stick
sudo shred -u /root/offsite.key
```
Put the two sticks in two different safe places. Whoever holds a stick can
read every backup: treat them like the keys to the building.

## 8. The first start

**▶**
```bash
cd /opt/motie
sudo docker compose --profile tools build
sudo docker compose up -d db
sudo docker compose run --rm tools alembic upgrade head
sudo docker compose up -d
sudo docker compose ps
```
`ps` should list `db`, `api`, `staff` and `caddy` as running (and `healthy`
for db and api). If the API keeps restarting, read why: **▶**
`sudo docker compose logs api | tail -20`. In office mode it stops at start-up
if `OFFICE_NETWORK`, `STAFF_PORTAL_KEY` or `MFA_SECRET_KEY` is missing, and
says which.

**The nightly backup**, at 02:00: **▶**
```bash
echo '0 2 * * * root cd /opt/motie && docker compose --profile tools run --rm backup >> /var/log/motie-backup.log 2>&1' | sudo tee /etc/cron.d/motie-backup
sudo docker compose --profile tools run --rm backup     # one now, to check
ls /mnt/motie-backup/daily/
```

**Keep Caddy's certificate authority** with `.env` on the key sticks, so a
rebuilt server needn't be trusted again by every PC: **▶**
```bash
sudo docker compose cp caddy:/data/caddy/pki/authorities/local ./caddy-ca
sudo cp -r ./caddy-ca /media/<the key stick>/ && sudo rm -rf ./caddy-ca
```

## 9. Trust the server's certificate (every PC and phone)

The server makes its own https certificates (Caddy's internal certificate
authority). Each device trusts it **once**; after that there is never a
warning. **If staff ever see a certificate warning, they must stop and call
ICT**: it may be a fake server.

**▶** Get the certificate onto a USB stick (or a shared folder):
```bash
cd /opt/motie
sudo docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt /media/<stick>/motie-office-ca.crt
```

- **Windows PCs:** double-click `motie-office-ca.crt` → *Install Certificate…*
  → *Local Machine* → *Place all certificates in the following store* →
  *Browse* → **Trusted Root Certification Authorities** → Finish. Restart the
  browser. (Firefox keeps its own list: *Settings → Privacy & Security →
  Certificates → View Certificates → Authorities → Import*.)
  ICT can push it to every PC with Group Policy instead.
- **Android:** copy the file to the phone, then *Settings → Security (and
  privacy) → More security settings → Encryption & credentials → Install a
  certificate → CA certificate* → choose the file.
- **iPhone/iPad:** send the file to the phone (AirDrop or email), open it,
  then *Settings → Profile Downloaded → Install*. Then **also** *Settings →
  General → About → Certificate Trust Settings* → turn it **on**.

Then open **https://etls.office** (your `OFFICE_HOSTNAME`): the staff login
page, with a padlock and no warning. In Chrome or Edge, the address bar offers
**Install**: the staff app then opens in its own window (step 12h).

## 10. Staff accounts and two-step sign-in

There are **no demo accounts** in office mode, and demo data can't be loaded.
Make each real account from the server, **with the person present**: the
command asks for their password, so let them type it themselves (at least 12
characters; a few words they'll remember). **▶**
```bash
cd /opt/motie
sudo docker compose run --rm tools python -m app.core.identity.cli create-user \
    --email fatou.ceesay@motie.gov.gm --name "Fatou Ceesay" --role records_officer
sudo docker compose run --rm tools python -m app.core.identity.cli assign-position \
    --email fatou.ceesay@motie.gov.gm --position records_officer
```
Roles and posts: `records_officer`, `minister`, `permanent_secretary`,
`director` (+ post `director_of_industry`), `officer` (+ `etls_desk_officer`
for the desk, `industry_officer`), `signatory_admin`, `absence_recorder`,
`stats_viewer`, `admin`. See docs/LEARNING.md, steps 4–5 and 10a. Give each
person only what their job needs.

**First sign-in, with the person present:** they open https://etls.office,
type their email and password, and are asked to **set up two-step sign-in**:
they install an authenticator app (Microsoft Authenticator, Google
Authenticator or Aegis), tap *Show my QR code*, scan it, and type the 6-digit
code. They then see **ten recovery codes**: they write them down or print
them, and keep them away from the phone.

**Staff without a smartphone** `[CONFIRM]` the procedure with the Ministry:
1. The **signatory admin** keeps an office authenticator device (a Ministry
   phone or tablet, locked away). The first sign-in is done together: the
   person types their password, the admin scans the QR code with the office
   device and reads out the code.
2. The **ten recovery codes** are printed, put in a **sealed envelope** with
   the person's name, and **held by the signatory admin**. Each working day the
   person receives **one** code (it works once, for one sign-in; a session
   lasts up to 8 hours), and the admin notes the date.
3. When three are left, the admin and the person make a new set together
   (*Security → Make new recovery codes*, with a code from the office device);
   the old ones stop working.
A cheaper long-term answer is a hardware key or a TOTP key fob (passkeys are
planned after Step 13: docs/GAPS.md).

**Lost phone and recovery codes:** check who it is, **in person**, then: **▶**
```bash
sudo docker compose run --rm tools python -m app.core.identity.cli reset-two-step --email them@motie.gov.gm
```
Their next sign-in sets up a new authenticator.

## 11. Import the historical register

The Excel register of past facility letters (step 11). It holds real importer
data: copy it from its USB stick to the server's own folder, **not** into
`/opt/motie`. **▶**
```bash
sudo mkdir -p /root/register && sudo cp /media/<stick>/register.xlsx /root/register/
cd /opt/motie
sudo bash scripts/import-history.sh /root/register/register.xlsx
```
It prints the totals the Statistics page will show (counts only). Run it again
to replace the import with a newer register.

## 12. The UPS: shutting down cleanly on a power cut

**What happens in a hard power cut without a UPS:** Postgres is safe. It
writes every change to its journal (the WAL) and makes sure it's on the disk
before it reports the change saved (`fsync`, `synchronous_commit` and
`full_page_writes` are on, and written out in docker-compose.office.yml so
nobody turns them off). On restart it replays the journal: nothing that was
confirmed to a staff member is lost. What *can* go wrong without a UPS: a
cheap disk lying about its write cache, the file system itself, or the
machine failing to come back. So: a UPS, and a clean shutdown.

**The UPS tells the server when its battery is low** (NUT, Network UPS Tools).
Plug its USB cable into the server. **▶**
```bash
sudo apt install -y nut
lsusb          # the UPS should be listed (APC, Eaton, CyberPower…)
```
**▶** `sudo nano /etc/nut/nut.conf`, set:
```
MODE=standalone
```
**▶** `sudo nano /etc/nut/ups.conf`, add at the end:
```
[ups]
    driver = usbhid-ups
    port = auto
    desc = "Server UPS"
```
**▶** `sudo nano /etc/nut/upsd.users`, add (make a password with `openssl rand -hex 16`):
```
[upsmon]
    password = <a password>
    upsmon primary
```
**▶** `sudo nano /etc/nut/upsmon.conf`, add:
```
MONITOR ups@localhost 1 upsmon <the same password> primary
SHUTDOWNCMD "/sbin/shutdown -h +0"
```
**▶** Start it and check it reads the UPS:
```bash
sudo systemctl restart nut-server nut-monitor
upsc ups@localhost | grep -E 'battery.charge|ups.status'
```
`ups.status: OL` means on mains ("on line"); `OB` on battery; `LB` low battery.
When the battery is low, NUT shuts the server down. Ubuntu stops Docker, which
gives Postgres up to 60 seconds to finish and close cleanly
(`stop_grace_period`). When the power is back, set the server to start by
itself: in the PC's BIOS, **"Restore on AC power loss" → "Power On"**.

**Test it once** (outside office hours): unplug the UPS from the wall and
watch `upsc ups@localhost ups.status` go to `OB`. Plug it back in. (A full
test, letting the battery run low, shuts the server down: do it only when
nobody is working.)

## 13. Daily, weekly and monthly checks

**Every morning (two minutes):**
- Sign in to https://etls.office. The home page shows a **backup warning** if
  the last backup is over 2 days old or can't be found: plug the drive back
  in, then tell ICT.
- **▶** `cd /opt/motie && sudo docker compose ps`: db, api, staff and caddy
  running (db and api `healthy`).
- **▶** `df -h / /mnt/motie-backup`: neither over 80 % full.
- **▶** `upsc ups@localhost ups.status`: `OL`.

**Every week (Friday):** swap the backup drives. **▶** `sudo umount /mnt/motie-backup`,
unplug, plug in the other drive, **▶** `sudo mount -a`. Take the first one
home or to the other office: that's the off-site copy (its `offsite/` folder
holds the encrypted weekly archives). A drive that's unplugged can't be
encrypted by ransomware.

**Every month:** a **restore drill** on a spare PC (sections 2–8 there, then
section 15). A backup nobody has restored is a hope, not a backup.
CI restores one automatically on every change to the code, but only on test
data.

## 14. Updates

Outside office hours (the update takes a backup first; if it fails it rolls
back, and work done since that backup is lost). **▶**
```bash
cd /opt/motie
sudo bash scripts/office-update.sh                 # the newest version
sudo bash scripts/office-update.sh --ref v1.4.0    # or a given one
```
It: backs up, gets and builds the new version, runs the migrations, starts
it, checks it over https, and **rolls back** to the old version and the
pre-update database if anything fails. See docs/LEARNING.md, step 13f.

**Offline (no internet at the office):** on a PC with internet, Git and
Docker, in a copy of the code: **▶**
```bash
bash scripts/office-bundle.sh v1.4.0 /media/<usb stick>
```
Take the stick to the server: **▶**
```bash
cd /media/<usb stick>/motie-update-v1.4.0 && sha256sum --check --quiet SHA256SUMS && cd /opt/motie
sudo bash scripts/office-update.sh --from /media/<usb stick>/motie-update-v1.4.0
```

**If an update fails** and the rollback didn't come up healthy either:
**▶** `sudo docker compose logs api | tail -50` and call the developer. The
backup it made is the newest folder in `/mnt/motie-backup/daily/`; section
15's restore puts it back.

## 15. If the server dies: rebuilding from a backup

You need: a new (or repaired) PC, a backup drive (or an off-site archive and
the **private key**), and the **`.env` copy and `caddy-ca` folder** from a key
stick.

1. Sections 2–5 on the new PC (Ubuntu, address and name, firewall, updates,
   Docker). Give it the **same fixed address**.
2. Section 6, but instead of making new secrets: **▶**
   `sudo cp /media/<key stick>/.env /opt/motie/.env && sudo chmod 600 /opt/motie/.env`.
3. Section 7's drive steps (mount the backup drive; it already has its marker).
4. **▶** Start the database and put Caddy's certificate authority back, so
   PCs and phones need not trust it again:
   ```bash
   cd /opt/motie
   sudo docker compose --profile tools build
   sudo docker compose up -d db caddy
   sudo docker compose cp /media/<key stick>/caddy-ca/. caddy:/data/caddy/pki/authorities/local/
   sudo docker compose restart caddy
   ```
5. **▶** Restore the newest backup (it checks it first, then replaces everything):
   ```bash
   ls /mnt/motie-backup/daily/
   sudo bash scripts/restore.sh /mnt/motie-backup/daily/<the newest>
   ```
   or, from an off-site archive:
   ```bash
   sudo bash scripts/restore.sh /media/<drive>/offsite/motie-<date>.tar.age --key /media/<key stick>/offsite.key
   ```
6. **▶** `sudo docker compose up -d` and sign in. Check the last few cases
   against paper: anything done after the backup was taken has to be entered
   again.
7. Section 8's cron line for the nightly backup, and section 12 (the UPS).

## 16. Phones on the office Wi-Fi

Records can scan documents with a phone (step 13g), and staff can use the app
on a phone.

- **The Wi-Fi:** phones must join the **office** Wi-Fi, in the
  `OFFICE_NETWORK` range; the staff app refuses other networks. If the office
  has a **guest** Wi-Fi, keep it on a **different** range, so visitors can't
  even reach the login page.
- **The certificate:** each phone trusts the server's certificate once
  (section 9, Android or iPhone).
- **Two-step sign-in on a phone:** the authenticator app can be on the same
  phone: sign in, switch to the authenticator, copy the code, switch back.
  For shared office phones or tablets, each person still has their own
  account and their own authenticator (or recovery codes, section 10):
  **never share an account**.
- **Install it:** in Chrome on Android, the menu offers **Install app**; on an
  iPhone, Safari's **Share → Add to Home Screen**.
- **Scanning:** open a case, tap **Scan with camera** under a document, take
  each page, check it, retake if blurred, then **Save as one PDF**. Nothing is
  kept on the phone.
- **Sign out** when done, and lock the phone with a PIN: a phone left signed
  in is a staff session (it ends after 30 idle minutes).
