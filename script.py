from collections import defaultdict, namedtuple
from datetime import datetime, timedelta
from pathlib import Path
import json
import subprocess

import attr

from git import Repo

Project = namedtuple("Project", ("name", "initial_commit", "branch", "paths"))

# Constants.
PROJECTS = (
    Project("synapse", "4f475c7697722e946e39e42f38f3dd03a95d8765", "develop", ("synapse", "tests")),
    Project("sydent", "2360cd427fb5cbebd34baa02ccb05ca2211eab63", "main", ("sydent", "tests")),
    Project("sygnal", "2eb2dd4eb6d83a17f260af02731940427e67feea", "main", ("sygnal", "tests")),
)

# Start at the nearest Monday.
LATEST_MONDAY = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
while LATEST_MONDAY.weekday():
    LATEST_MONDAY -= timedelta(days=1)


@attr.s(slots=True, auto_attribs=True)
class Result:
    # Total lines in the module.
    lines: int = 0
    # Precise and imprecise type hints.
    precise: int = 0
    imprecise: int = 0
    # The number of any type hints.
    any: int = 0
    # The number of empty lines.
    empty: int = 0
    # The number of lines skipped.
    unanalyzed: int = 0

    def __add__(self, other):
        self.lines += other.lines
        self.precise += other.precise
        self.imprecise += other.imprecise
        self.any += other.any
        self.empty += other.empty
        self.unanalyzed += other.unanalyzed
        return self


def search(root, paths):
    subprocess.run(
        ["mypy", "--lineprecision-report", "../.mypy-output", "--exclude", "synapse/storage/schema", *paths],
        capture_output=True,
        cwd=root)

    total = Result()
    by_module = defaultdict(Result)

    with open(".mypy-output/lineprecision.txt") as f:
        # Get rid of the first two lines.
        f.readline()
        f.readline()
        for line in f.readlines():
            parts = line.split()
            module = parts[0]
            current = Result(*map(int, parts[1:]))

            # Trim to the second-level module (e.g. foo.bar.* all gets grouped together).
            module = ".".join(module.split(".", 2)[:2])

            total += current
            by_module[module] += current

    return total, by_module

# The resulting output data.
#
# It is of the form of:
#
# {
#   "project": [
#     <commit hash>, <date as a string>, <total results>, <module result>
#   ]
# }
#
# Each of the results is of the form:
#
# [
#   <total>, <precise>, <imprecise>, <any>, <empty>, <unanalyzed>
# ]
data = {}

for project in PROJECTS:
    project_dir = Path(".") / project.name
    repo = Repo(project_dir)

    print(project.name)

    # Fetch updated changes.
    origin = repo.remotes[0]
    origin.fetch()

    # Start at the latest monday.
    day = LATEST_MONDAY

    # Iterate from the newest to the oldest commit.
    project_data = []
    for it, commit in enumerate(repo.iter_commits("origin/" + project.branch)):
        # Get the commit at the start of the day.
        committed_date = datetime.fromtimestamp(commit.committed_date)
        # Always include the latest commit, the earliest commit, and the last commit
        # of each Sunday.
        if committed_date < day or commit.hexsha == project.initial_commit or it == 0:
            # The next date will be a week in the past, if this is not the initial
            # commit.
            if it != 0:
                day -= timedelta(days=7)

            # Checkout this commit (why is this so hard?).
            repo.head.reference = commit
            repo.head.reset(index=True, working_tree=True)

            # Run mypy.
            total, by_module = search(project_dir, project.paths)

            print(commit, attr.astuple(total))

            project_data.append((
                commit.hexsha,
                str(committed_date),
                attr.astuple(total),
                {k: attr.astuple(v) for k, v in by_module.items()}
            ))

    # Empty line.
    print()

    # Store the results.
    data[project.name] = project_data

# Output the results.
with open("results.json", "w") as f:
    f.write(json.dumps(data, indent=4))
