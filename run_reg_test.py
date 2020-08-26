#!/usr/bin/env python3
"""
    Module for running regression tests
"""
from pathlib import Path
import sys
import argparse
import textwrap
import subprocess
from collections import OrderedDict
from prettytable import PrettyTable


# pylint: disable=wrong-import-position, import-error
sys.path.insert(
    0, str(Path(__file__).resolve().parent / "vtr_flow/scripts/python_libs")
)
sys.path.insert(0, str(Path(__file__).resolve().parent / "vtr_flow/scripts"))
from run_vtr_task import vtr_command_main as run_vtr_task
from vtr import (
    find_vtr_file,
    find_vtr_root,
    RawDefaultHelpFormatter,
)

# pylint: enable=wrong-import-position, import-error
BASIC_VERBOSITY = 1


def vtr_command_argparser(prog=None):
    """ Parses the arguments of run_reg_test """

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
        "-create_golden",
        default=False,
        action="store_true",
        help="Create golden reference results for the associated tasks",
    )

    parser.add_argument(
        "-check_golden",
        default=False,
        action="store_true",
        help="Check golden reference results for the associated tasks",
    )

    parser.add_argument(
        "-parse", default=False, action="store_true", help="Only run the parse tests.",
    )

    parser.add_argument(
        "-display_qor",
        default=False,
        action="store_true",
        help="Displays the previous Qor test results",
    )

    parser.add_argument(
        "-script",
        default="run_vtr_flow.py",
        help="Determines what flow script is used for the tests",
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
        "-calc_geomean",
        default=False,
        action="store_true",
        help="Enable the calculation of the task geomeans.",
    )

    parser.add_argument(
        "-show_failures",
        default=False,
        action="store_true",
        help="Produce additional debug output",
    )

    parser.add_argument(
        "-long_task_names",
        default=False,
        action="store_true",
        help="Display long task names",
    )

    return parser

def vtr_command_main(arg_list, prog=None):
    """
    Run the given regression tests
    """
    # Load the arguments
    args = vtr_command_argparser(prog).parse_args(arg_list)

    total_num_func_failures = 0
    total_num_qor_failures = 0
    for reg_test in args.reg_test:
        num_func_failures = 0
        num_qor_failures = 0
        if args.parse:
            num_qor_failures = parse_single_test(collect_task_list(reg_test))
        elif args.check_golden:
            num_qor_failures = 0
            parse_single_test(collect_task_list(arreg_testgs), check=True)
        elif args.create_golden:
            # Create golden results
            num_qor_failures = 0
            parse_single_test(collect_task_list(reg_test), create=True)
        elif args.calc_geomean:
            # Calculate geo mean values
            num_qor_failures = 0
            parse_single_test(collect_task_list(reg_test), calculate=True)
        elif args.display_qor:
            num_qor_failures = display_qor(reg_test)
        else:
            # Run any ODIN tests
            print("=============================================")
            print("    Verilog-to-Routing Regression Testing")
            print("=============================================")

            
            if reg_test.startswith("odin"):
                num_func_failures += run_odin_test(args, reg_test)

            # Collect the task lists
            vtr_task_list_files = collect_task_list(reg_test)

            # Run the actual tasks, recording functionality failures
            if len(vtr_task_list_files) > 0:
                num_func_failures += run_tasks(args, vtr_task_list_files)

            # Check against golden results
            if not args.skip_qor and len(vtr_task_list_files) > 0:
                num_qor_failures += parse_single_test(
                    vtr_task_list_files, check=True, calculate=True
                )
                print(
                    "\nTest '{}' had {} qor test failures".format(
                        reg_test, num_qor_failures
                    )
                )
            print("\nTest '{}' had {} run failures\n".format(reg_test, num_func_failures))
            total_num_func_failures += num_func_failures
            total_num_qor_failures += num_qor_failures
    # Final summary
    if total_num_func_failures == 0 and (total_num_qor_failures == 0 or args.skip_qor):
        print("All tests passed")
    elif total_num_func_failures != 0 or total_num_qor_failures != 0:
        print("Error: {} tests failed".format(total_num_func_failures + total_num_qor_failures))

    sys.exit(total_num_func_failures + total_num_qor_failures)


def display_qor(reg_test):
    """ Display the qor tests script files to be run outside of this script """
    test_dir = Path(find_vtr_root()) / "vtr_flow/tasks/regression_tests" / reg_test
    if not (test_dir / "qor_geomean.txt").is_file():
        print("QoR results do not exist ({}/qor_geomean.txt)".format(str(test_dir)))
        return 1
    print("=" * 121)
    print("\t" * 6, end="")
    print("{} QoR Results".format(reg_test))
    print("=" * 121)
    with (test_dir / "qor_geomean.txt").open("r") as results:
        data = OrderedDict()
        data["revision"] = [8, "", "{}"]
        data["date"] = [7, "", "{}"]
        data["total_runtime"] = [3, " s", "%.3f"]
        data["total_wirelength"] = [2, " units", "%.0f"]
        data["num_clb"] = [4, " blocks", "%.2f"]
        data["min_chan_width"] = [5, " tracks", "%.3f"]
        data["crit_path_delay"] = [6, " ns", "%.3f"]
        table = PrettyTable()
        table.field_names = list(data.keys())
        results.readline()
        for line in results.readlines():
            info = line.split()
            row = []
            for _, values in data.items():
                if len(info) - 1 < values[0]:
                    row += [""]
                else:
                    if values[2] == "{}" or not info[values[0]].isnumeric():
                        row += [("{}".format(info[values[0]])) + values[1]]
                    else:
                        row += [(values[2] % float(info[values[0]])) + values[1]]
            table.add_row(row)
        print(table)
    return 0


def run_odin_test(args, test_name):
    """ Run ODIN II test with given test name """
    odin_reg_script = [
        find_vtr_file("verify_odin.sh"),
        "--clean",
        "-C",
        find_vtr_file("output_on_error.conf"),
        "--nb_of_process",
        str(args.j),
        "--test",
        "{}/ODIN_II/regression_test/benchmark/".format(find_vtr_root()),
    ]
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
        print("FAILED test '{}'".format(test_name))
        return 1

    # Pass
    print("PASSED test '{}'".format(test_name))
    return 0


def collect_task_list(reg_test):
    """ create a list of task files """
    vtr_task_list_files = []
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
    return vtr_task_list_files


def run_tasks(args, task_lists):
    """Call 'run_vtr_task' with all the required arguments in the command"""
    print("Running {}".format(args.reg_test[0]))
    print(
        "-------------------------------------------------------------------------------"
    )
    vtr_task_cmd = ["-l"] + task_lists
    vtr_task_cmd += ["-j", str(args.j), "-script", args.script]
    if args.show_failures:
        vtr_task_cmd += ["-show_failures"]
    if not args.long_task_names:
        vtr_task_cmd += ["-short_task_names"]
    # Exit code is number of failures
    print("scripts/run_vtr_task.py {} \n".format(" ".join(map(str, vtr_task_cmd))))
    return run_vtr_task(vtr_task_cmd)


def parse_single_test(task_lists, check=True, calculate=True, create=False):
    """ parse the test results """
    vtr_task_cmd = ["-l"] + task_lists
    if check:
        vtr_task_cmd += ["-check_golden"]
    if calculate:
        vtr_task_cmd += ["-calc_geomean"]
    if create:
        vtr_task_cmd += ["-create_golden"]

    # Exit code is number of failures
    return run_vtr_task(vtr_task_cmd)


if __name__ == "__main__":
    vtr_command_main(sys.argv[1:])
