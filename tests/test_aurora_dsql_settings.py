"""Settings flags for Aurora DSQL (engine wiring is integration-tested against real AWS)."""

from unie_cortex.config import Settings


def test_use_aurora_dsql_true_when_host_set() -> None:
    s = Settings(
        mongodb_uri=None,
        aurora_dsql_cluster_host="abc.dsql.us-west-2.on.aws",
    )
    assert s.use_aurora_dsql is True


def test_use_aurora_dsql_false_when_host_empty() -> None:
    s = Settings(mongodb_uri=None, aurora_dsql_cluster_host=None)
    assert s.use_aurora_dsql is False


def test_mongodb_takes_precedence_over_dsql_flag() -> None:
    s = Settings(
        mongodb_uri="mongodb://localhost:27017",
        aurora_dsql_cluster_host="abc.dsql.us-west-2.on.aws",
    )
    assert s.use_mongodb is True
    assert s.use_aurora_dsql is True
