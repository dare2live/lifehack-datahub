"""Small CLI for DataHub prototype."""
from __future__ import annotations

import argparse

from .commands.admission import handle_admission_command, register_admission_commands
from .commands.career import handle_career_command, register_career_commands
from .commands.city import handle_city_command, register_city_commands
from .commands.operational import handle_operational_command, register_operational_commands
from .commands.outcome import handle_outcome_command, register_outcome_commands
from .commands.package import handle_package_command, register_package_commands
from .commands.reference import handle_reference_command, register_reference_commands
from .commands.score import handle_score_command, register_score_commands
from .commands.school import handle_school_command, register_school_commands
from .commands.update import handle_update_command, register_update_commands


def main() -> int:
    parser = argparse.ArgumentParser(prog="lifehack-datahub")
    sub = parser.add_subparsers(dest="cmd", required=True)

    register_package_commands(sub)

    register_school_commands(sub)

    register_admission_commands(sub)

    register_score_commands(sub)
    register_reference_commands(sub)

    register_outcome_commands(sub)
    register_career_commands(sub)
    register_city_commands(sub)

    register_update_commands(sub)

    register_operational_commands(sub)

    args = parser.parse_args()
    package_exit = handle_package_command(args)
    if package_exit is not None:
        return package_exit
    school_exit = handle_school_command(args)
    if school_exit is not None:
        return school_exit
    admission_exit = handle_admission_command(args)
    if admission_exit is not None:
        return admission_exit
    score_exit = handle_score_command(args)
    if score_exit is not None:
        return score_exit
    reference_exit = handle_reference_command(args)
    if reference_exit is not None:
        return reference_exit
    outcome_exit = handle_outcome_command(args)
    if outcome_exit is not None:
        return outcome_exit
    career_exit = handle_career_command(args)
    if career_exit is not None:
        return career_exit
    city_exit = handle_city_command(args)
    if city_exit is not None:
        return city_exit
    update_exit = handle_update_command(args)
    if update_exit is not None:
        return update_exit
    operational_exit = handle_operational_command(args)
    if operational_exit is not None:
        return operational_exit
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
