import argparse
import json

from .models import Principal
from .retrieval import sample_corpus
from .workflow import build_graph, run_query


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an offline, fictional tenant-scoped retrieval example")
    parser.add_argument("tenant", choices=("tenant-alpha", "tenant-beta"))
    parser.add_argument("query", help="A short search query over fictional sample documents")
    parser.add_argument("--profile", choices=("alpha-reader", "beta-reader"), default="alpha-reader")
    args = parser.parse_args()

    memberships = {
        "alpha-reader": frozenset({"tenant-alpha"}),
        "beta-reader": frozenset({"tenant-beta"}),
    }
    principal = Principal(args.profile, memberships[args.profile])
    result = run_query(build_graph(sample_corpus()), principal, args.tenant, args.query)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
