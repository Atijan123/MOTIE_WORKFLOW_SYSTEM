# The office server's backup and restore tools (step 13d): the same Postgres 16
# client as the database (pg_dump and pg_restore must match it), and age for
# the encrypted weekly archive. Built with the rest of the office stack.
FROM pgvector/pgvector:pg16
RUN apt-get update \
 && apt-get install -y --no-install-recommends age \
 && rm -rf /var/lib/apt/lists/*
COPY backup.sh restore-inside.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/backup.sh /usr/local/bin/restore-inside.sh
# Not the database's own entrypoint: this image only runs the scripts.
ENTRYPOINT []
CMD ["backup.sh"]
