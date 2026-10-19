"""The ETLS facility letter for imports: the etls schema, its form tables and its workflow.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-19

An importer asks the Ministry to tell the Gambia Revenue Authority (GRA) that
goods from an ECOWAS country qualify for ETLS treatment. Route:

    applicant submits -> Records confirms originals received -> ETLS desk
    verifies -> PS signs -> sent to GRA -> closed

This is the first module schema ("etls"). Module tables live there and point at
core.cases; core never reads them.
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

APP_ROLE = "motie_app"


def upgrade() -> None:
    # Workflows whose cases carry a module's form are opened through that
    # module's endpoint, never through the generic POST /cases (which would
    # create a case with no form).
    op.add_column("workflows", sa.Column("opened_by_module", sa.Text, nullable=True), schema="core")

    # [CONFIRM] The ETLS desk post: its title and department.
    op.execute(
        """
        INSERT INTO core.positions (code, title, department_id, reports_to_id)
        SELECT 'etls_desk_officer', 'ETLS Desk Officer', d.id, boss.id
        FROM core.departments d, core.positions boss
        WHERE d.code = 'industry_directorate' AND boss.code = 'director_of_industry'
        """
    )

    op.execute(
        """
        INSERT INTO core.workflows (code, name, start_role_id, opened_by_module)
        SELECT 'etls_facility_letter', 'ETLS facility letter (imports)', r.id, 'etls'
        FROM core.roles r WHERE r.code = 'applicant'
        """
    )
    op.execute(
        """
        INSERT INTO core.workflow_statuses (workflow_id, code, name, is_initial, is_final)
        SELECT w.id, s.code, s.name, s.is_initial, s.is_final
        FROM core.workflows w
        CROSS JOIN (VALUES
            ('submitted',          'Submitted',                     true,  false),
            ('originals_received', 'Originals received by Records', false, false),
            ('verified',           'Verified by the ETLS desk',     false, false),
            ('signed',             'Signed by the PS',              false, false),
            ('sent_to_gra',        'Sent to GRA',                   false, false),
            ('closed',             'Closed',                        false, true),
            ('rejected',           'Rejected',                      false, true)
        ) AS s(code, name, is_initial, is_final)
        WHERE w.code = 'etls_facility_letter'
        """
    )
    # [CONFIRM] Who reviews between the ETLS desk and the PS. For now the desk
    # sends verified files straight to the PS; a review step is one more status
    # and transition in a later migration.
    # [CONFIRM] Who sends the letter to GRA and closes the file, and who may
    # reject (placeholder: the ETLS desk, for all three).
    op.execute(
        """
        INSERT INTO core.workflow_transitions
            (workflow_id, from_status_id, to_status_id, required_position_id, name)
        SELECT w.id, f.id, t.id, p.id, x.name
        FROM (VALUES
            ('submitted',          'originals_received', 'records_officer',     'Confirm originals received'),
            ('originals_received', 'verified',           'etls_desk_officer',   'Verify'),
            ('originals_received', 'rejected',           'etls_desk_officer',   'Reject'),
            ('verified',           'signed',             'permanent_secretary', 'Sign the facility letter'),
            ('signed',             'sent_to_gra',        'etls_desk_officer',   'Send to GRA'),
            ('sent_to_gra',        'closed',             'etls_desk_officer',   'Close the file')
        ) AS x(from_code, to_code, position_code, name)
        JOIN core.workflows w ON w.code = 'etls_facility_letter'
        JOIN core.workflow_statuses f ON f.workflow_id = w.id AND f.code = x.from_code
        JOIN core.workflow_statuses t ON t.workflow_id = w.id AND t.code = x.to_code
        JOIN core.positions p ON p.code = x.position_code
        """
    )

    op.execute("CREATE SCHEMA etls")
    op.execute(f"GRANT USAGE ON SCHEMA etls TO {APP_ROLE}")

    # One row per facility letter case: the form the importer filled in.
    op.create_table(
        "facility_letters",
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("core.cases.id"), primary_key=True),
        sa.Column("importer_name", sa.Text, nullable=False),
        sa.Column("importer_address", sa.Text, nullable=False),
        sa.Column("product", sa.Text, nullable=False),
        # NUMERIC, not float: quantities are copied onto an official letter and
        # must come out exactly as typed (0.1 + 0.2 is not 0.3 in floating point).
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit", sa.Text, nullable=False),
        sa.Column("exporter_name", sa.Text, nullable=False),
        sa.Column("exporter_country", sa.Text, nullable=False),
        sa.Column("exporter_etls_approval_number", sa.Text, nullable=False),
        sa.CheckConstraint("quantity > 0", name="facility_letters_quantity_positive"),
        schema="etls",
    )
    # "One or more" of each: child tables, one row per number.
    op.create_table(
        "facility_letter_product_approvals",
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("etls.facility_letters.case_id"), primary_key=True),
        sa.Column("number", sa.Text, primary_key=True),
        schema="etls",
    )
    op.create_table(
        "facility_letter_certificates",
        sa.Column("case_id", sa.BigInteger, sa.ForeignKey("etls.facility_letters.case_id"), primary_key=True),
        # As the importer typed it, for the letter.
        sa.Column("number", sa.Text, nullable=False),
        # Upper-cased, spaces removed: what the duplicate check compares.
        sa.Column("number_normalized", sa.Text, primary_key=True),
        schema="etls",
    )
    # Finds earlier uses of a certificate number across all cases (step 6b).
    op.create_index(
        "facility_letter_certificates_number_idx",
        "facility_letter_certificates",
        ["number_normalized"],
        schema="etls",
    )

    # The form is written once, when the case is opened.
    op.execute(
        "GRANT SELECT, INSERT ON etls.facility_letters, etls.facility_letter_product_approvals, "
        f"etls.facility_letter_certificates TO {APP_ROLE}"
    )


def downgrade() -> None:
    op.drop_table("facility_letter_certificates", schema="etls")
    op.drop_table("facility_letter_product_approvals", schema="etls")
    op.drop_table("facility_letters", schema="etls")
    op.execute("DROP SCHEMA etls")
    for table in ("workflow_transitions", "workflow_statuses"):
        op.execute(
            f"""
            DELETE FROM core.{table}
            WHERE workflow_id = (SELECT id FROM core.workflows WHERE code = 'etls_facility_letter')
            """
        )
    op.execute("DELETE FROM core.workflows WHERE code = 'etls_facility_letter'")
    op.execute("DELETE FROM core.positions WHERE code = 'etls_desk_officer'")
    op.drop_column("workflows", "opened_by_module", schema="core")
