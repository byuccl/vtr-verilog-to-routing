#!/usr/bin/env python3
from pathlib import Path
from itertools import chain
import sys
import argparse
import textwrap
import subprocess
from datetime import datetime
# pylint: disable=wrong-import-position, import-error
sys.path.insert(
    0, str(Path(__file__).resolve().parent / "vtr_flow/scripts/python_libs")
)
sys.path.insert(
    0, str(Path(__file__).resolve().parent / "vtr_flow/scripts")
)
from run_vtr_task import vtr_command_main as run_vtr_task
from vtr import (
    find_vtr_file,
    print_verbose,
    find_vtr_root,
    format_elapsed_time,
    RawDefaultHelpFormatter,
    VERBOSITY_CHOICES,
)
# pylint: enable=wrong-import-position, import-error
BASIC_VERBOSITY = 1


def vtr_command_argparser(prog=None):
    description = textwrap.dedent(
        """
                    Runs one or more VTR regression tests.
                    """
    )
    epilog = textwrap.dedent(
        """
                Examples
                --------

                    Run the regression test 'vtr_reg_strong':

                        %(prog)s vtr_reg_strong

                    Run the regression tests 'vtr_reg_basic' and 'vtr_reg_strong':

                        %(prog)s vtr_reg_basic vtr_reg_strong

                    Run regression tests 'vtr_reg_basic' and 'vtr_reg_strong'
                    with 8 parallel workers:

                        %(prog)s vtr_reg_basic vtr_reg_strong -j8
                """
    )

    parser = argparse.ArgumentParser(
        prog=prog,
        description=description,
        epilog=epilog,
        formatter_class=RawDefaultHelpFormatter,
    )

    #
    # Major arguments
    #
    parser.add_argument(
        "reg_test",
        nargs="+",
        choices=[
            "vtr_reg_basic",
            "vtr_reg_strong",
            "vtr_reg_nightly",
            "vtr_reg_weekly",
            "odin_reg_full",
            "odin_reg_syntax",
            "odin_reg_arch",
            "odin_reg_operators",
            "odin_reg_large",
            "odin_reg",
            "odin_reg_micro",
            "vtr_reg_valgrind_small",
        ],
        help="Regression tests to be run",
    )

    parser.add_argument(
        "--create_golden",
        default=False,
        action="store_true",
        help="Create golden reference results for the associated tasks",
    )

    parser.add_argument(
        "-skip_qor",
        default=False,
        action="store_true",
        help="Skips running the Qor tests",
    )

    parser.add_argument(
        "-j",
        default=1,
        type=int,
        metavar="NUM_PROC",
        help="How many processors to use for execution.",
    )

    parser.add_argument(
        "-v",
        "--verbosity",
        choices=list(chain(VERBOSITY_CHOICES, [5])),
        default=2,
        type=int,
        help="Sets the verbosity of the script. Higher values produce more output.",
    )

    parser.add_argument(
        "--work_dir",
        default=None,
        help="Directory to store intermediate and result files."
        "If None, set to the relevante directory under $VTR_ROOT/vtr_flow/tasks.",
    )

    parser.add_argument(
        "-show_failures",
        default=False,
        action="store_true",
        help="Produce additional debug output",
    )

    parser.add_argument(
        "--debug",
        default=False,
        action="store_true",
        help="Produce additional debug output",
    )

    return parser


def main():
    vtr_command_main(sys.argv[1:])


def vtr_command_main(arg_list, prog=None):
    start = datetime.now()
    print("=============================================")
    print("    Verilog-to-Routing Regression Testing")
    print("=============================================")
    # Load the arguments
    args = vtr_command_argparser(prog).parse_args(arg_list)

    num_func_failures = 0
    num_qor_failures = 0

    try:
        if args.create_golden:
            # Create golden results
            num_qor_failures = 0
            create_tasks_golden_result(args, vtr_task_list_files)
        else:
            # Run any ODIN tests
            for reg_test in args.reg_test:
                if reg_test.startswith("odin"):
                    num_func_failures += run_odin_test(args, reg_test)

            # Collect the task lists
            vtr_task_list_files = []
            for reg_test in args.reg_test:
                if reg_test.startswith("vtr"):
                    task_list_filepath = str(
                        Path(find_vtr_root())
                        / "vtr_flow"
                        / "tasks"
                        / "regression_tests"
                        / reg_test
                        / "task_list.txt"
                    )
                    vtr_task_list_files.append(task_list_filepath)

            # Run the actual tasks, recording functionality failures
            num_func_failures += run_tasks(args, vtr_task_list_files)

            # Check against golden results
            if not args.skip_qor:
                num_qor_failures += check_tasks_qor(args, vtr_task_list_files)

        # Final summary
        print_verbose(BASIC_VERBOSITY, args.verbosity, "")
        if num_func_failures == 0 and (num_qor_failures == 0 or args.skip_qor):
            print_verbose(BASIC_VERBOSITY, args.verbosity, "PASSED All Test(s)")
        elif num_func_failures != 0 or num_qor_failures != 0:
            print_verbose(
                BASIC_VERBOSITY,
                args.verbosity,
                "FAILED {} functionality and {} QoR tests".format(
                    num_func_failures, num_qor_failures
                ),
            )

        sys.exit(num_func_failures + num_qor_failures)
    finally:
        print_verbose(
            BASIC_VERBOSITY,
            args.verbosity,
            "\n# {} took {} (exiting {})".format(
                prog,
                format_elapsed_time(datetime.now() - start),
                num_func_failures + num_qor_failures,
            ),
        )


def run_odin_test(args, test_name):
    odin_reg_script = [find_vtr_file("verify_odin.sh"), "--clean", "-C", find_vtr_file("output_on_error.conf"), "--nb_of_process", str(args.j), "--test", "{}/ODIN_II/regression_test/benchmark/".format(find_vtr_root())]
    if test_name == "odin_reg_full":
        odin_reg_script[-1] += "suite/full_suite"
    elif test_name == "odin_reg_syntax":
        odin_reg_script[-1] += "task/syntax"
    elif test_name == "odin_reg_arch":
        odin_reg_script[-1] += "task/arch_sweep"
    elif test_name == "odin_reg_operators":
        odin_reg_script[-1] += "task/operators"
    elif test_name == "odin_reg_large":
        odin_reg_script[-1] += "task/large"
    elif test_name == "odin_reg":
        odin_reg_script[-1] += "task/full"
    elif test_name == "odin_reg_micro":
        odin_reg_script[-1] += "suite/light_suite"

    odin_root = str(Path(odin_reg_script[0]).resolve().parent)

    result = subprocess.call(odin_reg_script, cwd=odin_root)

    assert result is not None
    if result != 0:
        # Error
        print_verbose(
            BASIC_VERBOSITY, args.verbosity, "FAILED test '{}'".format(test_name)
        )
        return 1

    # Pass
    print_verbose(BASIC_VERBOSITY, args.verbosity, "PASSED test '{}'".format(test_name))
    return 0


def run_tasks(args, task_lists):
    # Call 'vtr task'
    print("Running {}".format(args.reg_test[0]))
    print(
        "-------------------------------------------------------------------------------"
    )
    vtr_task_cmd = ["-l"] + task_lists
    vtr_task_cmd += [
        "-j",
        str(args.j),
        "-v",
        str(max(0, args.verbosity - 1)),
        "--print_metadata",
        str(args.debug),
    ]
    if args.show_failures:
        vtr_task_cmd += ["-show_failures"]
    if args.work_dir:
        vtr_task_cmd += ["--work_dir", args.workdir]

    # Exit code is number of failures
    return run_vtr_task(vtr_task_cmd)


def check_tasks_qor(args, task_lists):
    vtr_task_cmd = ["-l"] + task_lists
    vtr_task_cmd += [
        "-v",
        str(max(0, args.verbosity - 1)),
        "--check_golden",
        "--print_metadata",
        str(args.debug),
    ]
    if args.work_dir:
        vtr_task_cmd += ["--work_dir", args.workdir]

    # Exit code is number of failures
    return run_vtr_task(vtr_task_cmd)


def create_tasks_golden_result(args, task_lists):
    vtr_task_cmd = ["vtr", "task"]
    vtr_task_cmd += ["-l"] + task_lists
    vtr_task_cmd += [
        "-v",
        str(max(0, args.verbosity - 1)),
        "--create_golden",
        "--print_metadata",
        str(args.debug),
    ]
    if args.work_dir:
        vtr_task_cmd += ["--work_dir", args.workdir]

    # Exit code is number of failures
    return subprocess.call(vtr_task_cmd)


if __name__ == "__main__":
    main()
