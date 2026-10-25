"""Take "set your password" links out of the outbox's copy once they're no use.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-25

The outbox (core.notifications) kept each email exactly as written, link
included, so for up to PASSWORD_LINK_HOURS a database backup held working
links. Now:
- core.notifications.password_link_id says which link an email carries;
- a trigger replaces the link with "[link removed after sending]" in the
  same UPDATE that marks the email sent. A failed or waiting email keeps it,
  so a retry still sends a working link;
- core.scrub_expired_password_links() replaces the link in unsent emails
  whose link has expired ("[link removed after it expired]"). The worker
  calls it on every round, and doesn't send such emails.

The app still can't change what an email says: it has no UPDATE on body.
The trigger and the function (owned by motie_owner, SECURITY DEFINER) can
only ever remove a link.
"""
import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"
# The whole link: "https://.../set-password#token=abc...". The token never contains spaces.
LINK_PATTERN = r"\S*#token=\S+"


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("password_link_id", sa.BigInteger, sa.ForeignKey("core.password_links.id")),
        schema="core",
    )
    op.execute(
        f"""
        CREATE FUNCTION core.notifications_scrub_link_on_send() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.sent_at IS NULL AND NEW.sent_at IS NOT NULL AND NEW.password_link_id IS NOT NULL THEN
                NEW.body := regexp_replace(NEW.body, '{LINK_PATTERN}', '[link removed after sending]', 'g');
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER notifications_scrub_link_on_send
        BEFORE UPDATE OF sent_at ON core.notifications
        FOR EACH ROW EXECUTE FUNCTION core.notifications_scrub_link_on_send()
        """
    )
    # SECURITY DEFINER: runs with the owner's rights, so the app can call it
    # without UPDATE on body. A fixed search_path stops a caller slipping in
    # their own functions or tables under the same names.
    op.execute(
        f"""
        CREATE FUNCTION core.scrub_expired_password_links(as_of timestamptz DEFAULT now()) RETURNS integer
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, core AS $$
        DECLARE
            scrubbed integer;
        BEGIN
            UPDATE core.notifications n
            SET body = regexp_replace(n.body, '{LINK_PATTERN}', '[link removed after it expired]', 'g')
            FROM core.password_links l
            WHERE n.password_link_id = l.id AND n.sent_at IS NULL AND l.expires_at <= as_of
              AND n.body ~ '#token=';
            GET DIAGNOSTICS scrubbed = ROW_COUNT;
            RETURN scrubbed;
        END;
        $$
        """
    )
    op.execute("REVOKE EXECUTE ON FUNCTION core.scrub_expired_password_links(timestamptz) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION core.scrub_expired_password_links(timestamptz) TO {APP_ROLE}")
    # Links sent before this step: link them up, and scrub those already sent.
    op.execute(
        """
        UPDATE core.notifications n SET password_link_id = (a.details->>'link_id')::bigint
        FROM core.audit_log a
        WHERE n.audit_event_id = a.id AND a.action = 'user.password_link_sent'
        """
    )
    op.execute(
        f"""
        UPDATE core.notifications
        SET body = regexp_replace(body, '{LINK_PATTERN}', '[link removed after sending]', 'g')
        WHERE password_link_id IS NOT NULL AND sent_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION core.scrub_expired_password_links(timestamptz)")
    op.execute("DROP TRIGGER notifications_scrub_link_on_send ON core.notifications")
    op.execute("DROP FUNCTION core.notifications_scrub_link_on_send()")
    op.drop_column("notifications", "password_link_id", schema="core")
