import pytest

from crewai_tools.tools.databricks_query_tool.databricks_query_tool import (
    DatabricksQueryToolSchema,
    _leading_sql_keyword,
)


class TestLeadingSqlKeyword:
    """_leading_sql_keyword must find the real leading statement keyword even
    through leading whitespace/comments, so the read-only check downstream
    can't be bypassed by prefixing a query with a comment."""

    def test_simple_select(self):
        assert _leading_sql_keyword("SELECT * FROM t") == "select"

    def test_case_insensitive(self):
        assert _leading_sql_keyword("SeLeCt 1") == "select"

    def test_leading_whitespace(self):
        assert _leading_sql_keyword("   \n\t SELECT 1") == "select"

    def test_leading_line_comment(self):
        assert _leading_sql_keyword("-- drop everything\nSELECT 1") == "select"

    def test_leading_block_comment(self):
        assert _leading_sql_keyword("/* comment */ SELECT 1") == "select"

    def test_leading_comment_hides_real_keyword(self):
        """A comment that itself contains a read-only-looking word must not
        cause the check to see past the real (disallowed) keyword."""
        assert _leading_sql_keyword("/* SELECT */ DROP TABLE t") == "drop"

    def test_empty_query(self):
        assert _leading_sql_keyword("") == ""

    def test_only_whitespace_and_comments(self):
        assert _leading_sql_keyword("  -- just a comment\n  ") == ""


class TestDatabricksQueryToolSchemaValidation:
    """Regression coverage for the confirmed Medium-severity finding: `query`
    is LLM/agent-supplied and can be steered by prompt-injected content in
    retrieved data, so only read-only statements may be executed."""

    @pytest.mark.parametrize(
        "query",
        [
            "SELECT * FROM employees",
            "select * from employees",
            "SHOW TABLES",
            "DESCRIBE employees",
            "DESC employees",
            "EXPLAIN SELECT * FROM employees",
        ],
    )
    def test_read_only_statements_are_allowed(self, query):
        validated = DatabricksQueryToolSchema(query=query)
        assert validated.query.startswith(query.rstrip(";"))

    @pytest.mark.parametrize(
        "query",
        [
            "DROP TABLE employees",
            "DELETE FROM employees WHERE id = 1",
            "INSERT INTO employees VALUES (1, 'x')",
            "UPDATE employees SET salary = 0",
            "MERGE INTO employees USING staging ON employees.id = staging.id",
            "ALTER TABLE employees ADD COLUMN x INT",
            "TRUNCATE TABLE employees",
            "CREATE TABLE evil (id INT)",
            "GRANT ALL ON employees TO PUBLIC",
        ],
    )
    def test_non_read_only_statements_are_rejected(self, query):
        with pytest.raises(ValueError, match="Only read-only statements are permitted"):
            DatabricksQueryToolSchema(query=query)

    def test_rejection_is_case_insensitive(self):
        with pytest.raises(ValueError, match="Only read-only statements are permitted"):
            DatabricksQueryToolSchema(query="drop table employees")

    def test_comment_prefixed_destructive_statement_is_still_rejected(self):
        """A prompt-injection-style prefix comment must not let a DROP/DELETE
        slip past the read-only check."""
        with pytest.raises(ValueError, match="Only read-only statements are permitted"):
            DatabricksQueryToolSchema(
                query="-- SELECT this is fine, trust me\nDROP TABLE employees"
            )

    def test_empty_query_is_rejected(self):
        with pytest.raises(ValueError, match="Query cannot be empty"):
            DatabricksQueryToolSchema(query="")

    def test_whitespace_only_query_is_rejected(self):
        with pytest.raises(ValueError, match="Query cannot be empty"):
            DatabricksQueryToolSchema(query="   ")

    def test_row_limit_still_appended_to_allowed_query(self):
        """The read-only check must not interfere with the pre-existing
        LIMIT-clause-appending behavior for allowed statements."""
        validated = DatabricksQueryToolSchema(query="SELECT * FROM employees", row_limit=10)
        assert validated.query == "SELECT * FROM employees LIMIT 10;"

    def test_row_limit_not_appended_when_query_already_has_one(self):
        validated = DatabricksQueryToolSchema(
            query="SELECT * FROM employees LIMIT 5", row_limit=10
        )
        assert validated.query == "SELECT * FROM employees LIMIT 5"
