# office/keys

Put the off-site **public** key here as `offsite.pub` (one line, starting
`age1...`). The nightly backup uses it to encrypt the weekly archive.

The matching **private** key must never be on the server: keep it on a USB
stick in a safe, and a second copy elsewhere (docs/OFFICE-SETUP.md, "Backups").
Anyone with the private key can read every backup.
