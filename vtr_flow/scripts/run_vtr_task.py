#!/usr/bin/env python3
from pathlib import Path
from pathlib import PurePath
import sys
import argparse
import itertools
import textwrap
import subprocess
import time
import shutil
from datetime import datetime
import multiprocessing
from contextlib import redirect_stdout
from multiprocessing import Process, Queue, Pool, Manager
from run_vtr_flow import vtr_command_main as run_vtr_flow

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python_libs'))

from vtr import load_list_file, find_vtr_file, print_verbose, find_vtr_root, CommandRunner, format_elapsed_time, RawDefaultHelpFormatter, VERBOSITY_CHOICES, argparse_str2bool, get_next_run_dir, get_latest_run_dir, load_task_config, TaskConfig, find_task_config_file, CommandRunner, load_pass_requirements, load_parse_results, parse_vtr_flow, load_script_param, get_latest_run_number
from vtr.error import VtrError, InspectError, CommandError

BASIC_VERBOSITY = 1
FAILED_LOG_VERBOSITY = 2
ALL_LOG_VERBOSITY = 4

class Job:

    def __init__(self, task_name, arch, circuit, work_dir, run_command, parse_command, second_parse_command, qor_parse_command):
        self._task_name = task_name
        self._arch = arch
        self._circuit = circuit
        self._run_command = run_command
        self._parse_command = parse_command
        self._second_parse_command = second_parse_command
        self._qor_parse_command = qor_parse_command
        self._work_dir = work_dir

    def task_name(self):
        return self._task_name

    def arch(self):
        return self._arch

    def circuit(self):
        return self._circuit

    def job_name(self):
        return str(PurePath(self.arch()).joinpath(self.circuit()))

    def run_command(self):
        return self._run_command

    def parse_command(self):
        return self._parse_command

    def second_parse_command(self):
        return self._second_parse_command
    
    def qor_parse_command(self):
        return self._qor_parse_command
        
    def work_dir(self, run_dir):
        return str(PurePath(run_dir).joinpath(self._work_dir))

def vtr_command_argparser(prog=None):
    description = textwrap.dedent(
                    """
                    Runs one or more VTR tasks.
                    """
                  )
    epilog = textwrap.dedent(
                """
                Examples
                --------

                    Run the task named 'timing_chain':

                        %(prog)s timing_chain

                    Run all the tasks listed in the file 'task_list.txt':

                        %(prog)s -l task_list.txt

                    Run 'timing_chain' with 4 jobs running in parallel:

                        %(prog)s timing_chain -j4

                Exit Code
                ---------
                    The exit code equals the number failures (i.e. exit code 0 indicates no failures).
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
    parser.add_argument('task',
                        nargs="*",
                        help="Tasks to be run")

    parser.add_argument('-l', '--list_file',
                        nargs="*",
                        default=[],
                        metavar="TASK_LIST_FILE",
                        help="A file listing tasks to be run")

    parser.add_argument("-parse",
                        default=False,
                        action="store_true",
                        dest="parse",
                        help="Perform only parsing on the latest task run")

    parser.add_argument("-create_golden",
                        default=False,
                        action="store_true",
                        dest="create_golden",
                        help="Update or create golden results for the specified task")

    parser.add_argument("-check_golden",
                        default=False,
                        action="store_true",
                        dest="check_golden",
                        help="Check the latest task run against golden results")

    parser.add_argument('-system',
                        choices=['local'],
                        default='local',
                        help="What system to run the tasks on.")

    parser.add_argument("-show_failures",
                        default=False,
                        action="store_true",
                        help="Produce additional debug output")

    parser.add_argument('-j',
                        default=1,
                        type=int,
                        metavar="NUM_PROC",
                        help="How many processors to use for execution.")

    parser.add_argument('-timeout',
                        default=30*24*60*60, #30 days
                        metavar="TIMEOUT_SECONDS",
                        help="Time limit for this script.")

    parser.add_argument("-v", "--verbosity",
                        choices=VERBOSITY_CHOICES,
                        default=2,
                        type=int,
                        help="Sets the verbosity of the script. Higher values produce more output.")
    
    parser.add_argument("-minw_hint_factor",
                        default=1,
                        type=float,
                        help="Minimum width hint factor to multiplied by the minimum width hint")

    parser.add_argument("--work_dir",
                        default=None,
                        help="Directory to store intermediate and result files."
                             "If None, set to the relevant directory under $VTR_ROOT/vtr_flow/tasks.")
    
    parser.add_argument("-revision",
                        default="",
                        help="Revision number")

    parser.add_argument("-calc_geomean",
                        default=False,
                        action="store_true",
                        help="QoR geomeans are not computed by default")

    parser.add_argument("-print_metadata",
                        default=True,
                        type=argparse_str2bool,
                        help="Print meta-data like command-line arguments and run-time")

    return parser

def main():
    vtr_command_main(sys.argv[1:])

def vtr_command_main(arg_list, prog=None):
    start = datetime.now()

    #Load the arguments
    args = vtr_command_argparser(prog).parse_args(arg_list)

    args.run = True
    if args.parse or args.create_golden or args.check_golden or args.calc_geomean:
        #Don't run if parsing or handling golden results
        args.run = False

    if args.run:
        #Always parse if running
        args.parse = True

    if args.print_metadata:
        print ("# {} {}\n".format(prog, ' '.join(arg_list)))

    num_failed = -1
    try:
        task_names = args.task

        for list_file in args.list_file:
            task_names += load_list_file(list_file)

        config_files = [find_task_config_file(task_name) for task_name in task_names]

        configs = [load_task_config(config_file) for config_file in config_files]

        num_failed = run_tasks(args, configs)

    except CommandError as e:
        print ("Error: {msg}".format(msg=e.msg))
        print ("\tfull command: ", e.cmd)
        print ("\treturncode  : ", e.returncode)
        print ("\tlog file    : ", e.log)
    except InspectError as e:
        print ("Error: {msg}".format(msg=e.msg))
        if e.filename:
            print ("\tfile: ", e.filename)
    except VtrError as e:
        print ("Error:", e.msg)
    finally:
        if args.print_metadata:
            print ("\n# {} took {} (exiting {})".format(prog, format_elapsed_time(datetime.now() - start), num_failed))
    if(__name__=="main"):
        sys.exit(num_failed)
    return num_failed

def run_tasks(args, configs):
    """
    Runs the specified set of tasks (configs)
    """
    num_failed = 0

    #We could potentially support other 'run' systems (e.g. a cluster),
    #rather than just the local machine
    if args.system == "local":
        assert args.j > 0, "Invalid number of processors"

        #Generate the jobs, each corresponding to an invocation of vtr flow
        jobs = create_jobs(args, configs)

        if args.run:
            num_failed = run_parallel(args, configs, jobs)

        if args.parse:
            print_verbose(BASIC_VERBOSITY, args.verbosity, "")
            parse_tasks(args, configs, jobs)

        if args.create_golden:
            print_verbose(BASIC_VERBOSITY, args.verbosity, "")
            create_golden_results_for_tasks(args, configs)

        if args.check_golden:
            print_verbose(BASIC_VERBOSITY, args.verbosity, "")
            num_failed += check_golden_results_for_tasks(args, configs)
        
        if args.calc_geomean:
            summarize_qor(args, configs)
            calc_geomean(args, configs)

    else:
        raise VtrError("Unrecognized run system {system}".format(system=args.system))

    return num_failed


def create_golden_results_for_tasks(args, configs):
    for config in configs:
        create_golden_results_for_task(args, config)

def create_golden_results_for_task(args, config):
    """
    Copies the latest task run's parse_results.txt into the config directory as golden_results.txt
    """
    run_dir = find_latest_run_dir(args, config)

    task_results = str(PurePath(run_dir).joinpath("parse_results.txt"))
    golden_results_filepath = str(PurePath(config.config_dir).joinpath("golden_results.txt"))

    print_verbose(BASIC_VERBOSITY, args.verbosity, "Creating golden task results from {} -> {}".format(run_dir, golden_results_filepath))

    shutil.copy(task_results, golden_results_filepath)

def check_golden_results_for_tasks(args, configs):
    num_qor_failures = 0

    print_verbose(BASIC_VERBOSITY, args.verbosity, "Checking QoR:")
    for config in configs:
        num_qor_failures += check_golden_results_for_task(args, config)

    return num_qor_failures

def check_golden_results_for_task(args, config):
    """
    Copies the latest task run's parse_results.txt into the config directory as golden_results.txt
    """
    num_qor_failures = 0
    run_dir = find_latest_run_dir(args, config)

    if not config.pass_requirements_file:
        print_verbose(BASIC_VERBOSITY, args.verbosity, 
                      "Warning: no pass requirements file for task {}, QoR will not be checked".format(config.task_name))
    else:

        #Load the pass requirements file

        #Load the task's parse results
        task_results_filepath = str(PurePath(run_dir).joinpath("parse_results.txt"))
        task_results = load_parse_results(task_results_filepath)
         
        #Load the golden reference
        if config.second_parse_file:
            second_results_filepath = str(PurePath(config.config_dir).joinpath("parse_results_2.txt"))
            second_results = load_parse_results(second_results_filepath)
            num_qor_failures = check_two_files(args, config, run_dir, task_results, task_results_filepath, second_results, second_results_filepath,  second_name = "second parse file")
            
            check_string = "second parse file results"
        else:
            golden_results_filepath = str(PurePath(config.config_dir).joinpath("golden_results.txt"))
            golden_results = load_parse_results(golden_results_filepath)
            num_qor_failures = check_two_files(args, config, run_dir, task_results, task_results_filepath, golden_results, golden_results_filepath)
        
        

    if num_qor_failures == 0:
        print_verbose(BASIC_VERBOSITY, args.verbosity, 
                      "    PASSED {} {}".format(PurePath(run_dir).name, config.task_name))

    return num_qor_failures

def check_two_files(args, config, run_dir, first_results, first_results_filepath, second_results, second_results_filepath, first_name = "task", second_name = "golden"):
    #Verify that the architecture and circuit are specified
    for param in ["architecture", "circuit", "script_params"]:
        if param not in first_results.primary_keys():
            raise InspectError("Required param '{}' missing from {} results: {}".format(param, first_name, first_results_filepath), first_results_filepath)

        if param not in second_results.primary_keys():
            raise InspectError("Required param '{}' missing from {} results: {}".format(param, second_first, second_results_filepath), second_results_filepath)

    #Verify that all params and pass requirement metric are included in both the  result files
    # We do not worry about non-pass_requriements elements being different or missing
    pass_req_filepath = str(PurePath(find_vtr_root()) / 'vtr_flow' / 'parse' / 'pass_requirements'/ config.pass_requirements_file)
    pass_requirements = load_pass_requirements(pass_req_filepath)

    for metric in pass_requirements.keys():
        for (arch, circuit, script_params), result in first_results.all_metrics().items():
            if metric not in result:
                raise InspectError("Required metric '{}' missing from {} results".format(metric, first_name), first_results_filepath) 

        for (arch, circuit, script_params), result in second_results.all_metrics().items():
            if metric not in result:
                raise InspectError("Required metric '{}' missing from {} results".format(metric, second_name), second_results_filepath) 

    #Load the primary keys for result files
    second_primary_keys = []
    for (arch, circuit, script_params), metrics in second_results.all_metrics().items():
        second_primary_keys.append((arch, circuit,script_params))

    first_primary_keys = []
    for (arch, circuit,script_params), metrics in first_results.all_metrics().items():
        first_primary_keys.append((arch, circuit,script_params))

    #Ensure that first result file  has all the second result file cases
    for arch, circuit, script_params in second_primary_keys:
        if first_results.metrics(arch, circuit,script_params) == None:
            raise InspectError("Required case {}/{} missing from {} results: {}".format(arch, circuit, first_name, first_results_filepath))

    #Warn about any elements in first result file that are not found in second result file
    for arch, circuit, script_params in first_primary_keys:
        if second_results.metrics(arch, circuit,script_params) == None:
            print_verbose(BASIC_VERBOSITY, args.verbosity,
                            "Warning: {} includes result for {}/{} missing in {} results".format(first_name, arch, circuit, second_name))
    num_qor_failures = 0
    #Verify that the first results pass each metric for all cases in the second results 
    for (arch, circuit, script_params) in second_primary_keys:
        second_metrics = second_results.metrics(arch, circuit, script_params)
        first_metrics = first_results.metrics(arch, circuit, script_params)

        for metric in pass_requirements.keys():

            if not metric in second_metrics:
                print_verbose(BASIC_VERBOSITY, args.verbosity, "Warning: Metric {} missing from {} results".format(metric, second_name))
                continue

            if not metric in first_metrics:
                print_verbose(BASIC_VERBOSITY, args.verbosity, "Warning: Metric {} missing from {} results".format(metric, first_name))
                continue

            try:
                metric_passed, reason = pass_requirements[metric].check_passed(second_metrics[metric], first_metrics[metric], second_name)
            except InspectError as e:
                metric_passed = False
                reason = e.msg

            if not metric_passed:
                print_verbose(BASIC_VERBOSITY, args.verbosity, "    FAILED {} {} {}/{}: {} {}".format(PurePath(run_dir).name, config.task_name, arch, circuit, metric, reason))
                num_qor_failures += 1
    return num_qor_failures

def create_jobs(args, configs):
    jobs = []
    for config in configs:
        for arch, circuit in itertools.product(config.archs, config.circuits):
            golden_results_filepath = str(PurePath(config.config_dir).joinpath("golden_results.txt"))
            golden_results = load_parse_results(golden_results_filepath)
            abs_arch_filepath = resolve_vtr_source_file(config, arch, config.arch_dir)
            abs_circuit_filepath = resolve_vtr_source_file(config, circuit, config.circuit_dir)  
            work_dir = str(PurePath(arch).joinpath(circuit))         
            run_dir = str(Path(get_next_run_dir(find_task_dir(args,config))) / work_dir)
            #Collect any extra script params from the config file
            cmd = [abs_circuit_filepath, abs_arch_filepath]           

            if args.show_failures:
                cmd += ["-show_failures"]
            cmd += ["-name","{}:\t\t\t{}".format(config.task_name.split("_", 1)[1],work_dir)]
            cmd += config.script_params if config.script_params else []
            cmd += config.script_params_common if config.script_params_common else []
                    
                    
            #Apply any special config based parameters
            if config.cmos_tech_behavior:
                cmd += ["-cmos_tech", resolve_vtr_source_file(config, config.cmos_tech_behavior, "tech")]

            if config.pad_file:
                cmd += ["--fix_pins", resolve_vtr_source_file(config, config.pad_file)]
            
            if config.sdc_dir:
                cmd += ["-sdc_file","{}/{}.sdc".format(config.sdc_dir, Path(circuit).stem)]
            
            parse_cmd = None
            second_parse_cmd = None
            qor_parse_command = None
            if config.parse_file:
                parse_cmd = [resolve_vtr_source_file(config, config.parse_file, str(PurePath("parse").joinpath("parse_config")))]

            if config.second_parse_file:
                second_parse_cmd = [resolve_vtr_source_file(config, config.second_parse_file, str(PurePath("parse").joinpath("parse_config")))]
            
            if config.qor_parse_file:
                qor_parse_command = [resolve_vtr_source_file(config, config.qor_parse_file, str(PurePath("parse").joinpath("qor_config")))]
            #We specify less verbosity to the sub-script
            # This keeps the amount of output reasonable
            if max(0, args.verbosity - 1):
                cmd += ["-verbose"]
            if config.script_params_list_add:
                for value in config.script_params_list_add:
                    temp_dir = run_dir + "/common_{}".format(value.replace(" ", "_"))
                    cmd += ["-temp_dir", temp_dir]
                    expected_min_W = ret_expected_min_W(circuit, arch, golden_results, value)
                    expected_min_W = int(expected_min_W * args.minw_hint_factor)
                    expected_min_W += expected_min_W % 2
                    if expected_min_W > 0:
                        cmd += ["--min_route_chan_width_hint", str(expected_min_W)] 
                    expected_vpr_status = ret_expected_vpr_status(arch, circuit, golden_results, value)
                    if (expected_vpr_status != "success" and expected_vpr_status != "Unknown"):
                        cmd += ["-expect_fail", expected_vpr_status]
                    current_parse_cmd = parse_cmd.copy()
                    
                    if config.parse_file:
                        current_parse_cmd += ["arch={}".format(arch),"circuit={}".format(circuit),"script_params={}".format(load_script_param(value))]
                        current_parse_cmd.insert(0,run_dir+"/{}".format(load_script_param(value)))
                    current_second_parse_cmd = second_parse_cmd.copy() if second_parse_cmd else None
                    
                    if config.second_parse_file:
                        current_second_parse_cmd += ["arch={}".format(arch),"circuit={}".format(circuit),"script_params={}".format(load_script_param(value))]
                        current_second_parse_cmd.insert(0,run_dir+"/{}".format(load_script_param(value)))
                    current_qor_parse_command = qor_parse_command.copy() if qor_parse_command else None

                    if config.qor_parse_file:
                        current_qor_parse_command += ["arch={}".format(arch),"circuit={}".format(circuit),"script_params={}".format("common")]
                        current_qor_parse_command.insert(0,run_dir+"/{}".format(load_script_param(value)))

                    jobs.append(Job(config.task_name, arch, circuit, work_dir + "/{}".format(load_script_param(value)), cmd + value.split(" "), current_parse_cmd, current_second_parse_cmd, current_qor_parse_command))
            else:
                cmd += ["-temp_dir", run_dir + "/common"]
                expected_min_W = ret_expected_min_W(circuit, arch, golden_results)
                expected_min_W = int(expected_min_W * args.minw_hint_factor)
                expected_min_W += expected_min_W % 2
                if expected_min_W > 0:
                    cmd += ["--min_route_chan_width_hint", str(expected_min_W)] 
                expected_vpr_status = ret_expected_vpr_status(arch, circuit, golden_results)
                if (expected_vpr_status != "success" and expected_vpr_status != "Unknown"):
                    cmd += ["-expect_fail", expected_vpr_status]
                if config.parse_file:
                    parse_cmd += ["arch={}".format(arch),"circuit={}".format(circuit),"script_params={}".format("common")]
                    parse_cmd.insert(0,run_dir+"/common")

                if config.second_parse_file:
                    second_parse_cmd += ["arch={}".format(arch),"circuit={}".format(circuit),"script_params={}".format("common")]
                    second_parse_cmd.insert(0,run_dir+"/common")\

                if config.qor_parse_file:
                    qor_parse_command += ["arch={}".format(arch),"circuit={}".format(circuit),"script_params={}".format("common")]
                    qor_parse_command.insert(0,run_dir+"/common")

                jobs.append(Job(config.task_name, arch, circuit, work_dir + "/common", cmd, parse_cmd, second_parse_cmd, qor_parse_command))
                
    return jobs

def summarize_qor(args, configs):
    first = True 
    task_path = Path(configs[0].config_dir).parent
    output_path = task_path
    if len(configs) > 1 or (task_path.parent / "task_list.txt").is_file():
        output_path = task_path.parent
    output_path = output_path / "task_summary"
    output_path.mkdir(exist_ok=True)
    out_file = output_path / (str(Path(find_latest_run_dir(args, configs[0])).stem) + "_summary.txt")
    with out_file.open("w+") as out:
        for config in configs:
            with (Path(find_latest_run_dir(args, config)) / "qor_results.txt").open("r") as in_file:
                headers = in_file.readline()
                if first:
                    print("task_name \t{}".format(headers), file = out, end="")
                    first = False
                for line in in_file:
                    print("{}\t{}".format(config.task_name,line), file = out, end="")

def calc_geomean(args, configs):
    first = False 
    task_path = Path(configs[0].config_dir).parent
    output_path = task_path
    if len(configs) > 1 or (task_path.parent / "task_list.txt").is_file():
        output_path = task_path.parent
    out_file = output_path /  "qor_geomean.txt"
    if not out_file.is_file():
        first = True
    summary_file = output_path / "task_summary" / (str(Path(find_latest_run_dir(args, configs[0])).stem) + "_summary.txt")

    with out_file.open("w" if first else "a") as out:
        with summary_file.open("r") as summary:
            header = summary.readline().strip()
            params = header.split("\t")[4:]
            if first:
                print("run",file=out,end="\t")
                for param in params:
                    print(param,file=out,end="\t")
                print("date\trevision",file=out)
                first = False
            lines = summary.readlines()
            print(get_latest_run_number(str(Path(configs[0].config_dir).parent)),file=out,end="\t")
            for index in range(len(params)):
                geo_mean = 1
                num = 0
                previous_value = None
                for line in lines:
                    line = line.split("\t")[4:]
                    current_value = line[index]
                    try:
                        if float(current_value) > 0:
                            geo_mean *= float(current_value)
                            num+=1
                    except ValueError:
                        if not previous_value:
                            previous_value = current_value
                        elif current_value != previous_value:
                            previous_value = "-1"
                if num:
                    geo_mean **= 1/num
                    print(geo_mean,file=out,end="\t")
                else:
                    print(previous_value if previous_value is not None else "-1",file=out,end="\t")
        print(datetime.date(datetime.now()),file=out,end="\t")
        print(args.revision,file=out)


def find_latest_run_dir(args, config):
    task_dir = find_task_dir(args, config)

    run_dir = get_latest_run_dir(task_dir)

    if not run_dir:
        raise InspectError("Failed to find run directory for task '{}' in '{}'".format(config.task_name, task_dir))

    assert Path(run_dir).is_dir()

    return run_dir

def find_task_dir(args, config):
    task_dir = None
    if args.work_dir:
        task_dir = str(PurePath(args.work_dir).joinpath(config.task_name))

    else:
        #Task dir is just above the config directory
        task_dir = Path(config.config_dir).parent
        assert task_dir.is_dir

    return str(task_dir)

def ret_expected_min_W(circuit, arch, golden_results, script_params=None):
    script_params = load_script_param(script_params)
    golden_metrics = golden_results.metrics(arch,circuit,script_params)
    if golden_metrics and "min_chan_width" in golden_metrics:
        return int(golden_metrics["min_chan_width"])
    return -1

def ret_expected_vpr_status(arch, circuit, golden_results, script_params=None):
    script_params = load_script_param(script_params)
    golden_metrics = golden_results.metrics(arch,circuit,script_params)
    if not golden_metrics or 'vpr_status' not in golden_metrics :
        return "Unknown"

    return golden_metrics['vpr_status']

def run_parallel(args, configs, queued_jobs):
    """
    Run each external command in commands with at most args.j commands running in parllel
    """
    #Determine the run dir for each config
    run_dirs = {}
    for config in configs:
        task_dir = find_task_dir(args, config)
        task_run_dir = get_next_run_dir(task_dir)
        run_dirs[config.task_name] = task_run_dir


    #We pop off the jobs of queued_jobs, which python does from the end,
    #so reverse the list now so we get the expected order. This also ensures
    #we are working with a copy of the jobs
    queued_jobs = list(reversed(queued_jobs))
    #Find the max taskname length for pretty printing
    max_taskname_len = 0
    for job in queued_jobs:
        max_taskname_len = max(max_taskname_len, len(job.task_name()))

    queued_procs = []
    queue = Manager().Queue()
    for job in queued_jobs:
        queued_procs += [(queue, run_dirs, job)]
    #Queue of currently running subprocesses

    num_failed = 0
    with Pool(processes=args.j) as pool:
        print("\n\n processors: {} \n\n".format(multiprocessing.cpu_count()))
        pool.starmap(run_vtr_flow_process,queued_procs)
        pool.close()
        pool.join()
    for proc in queued_procs:
        num_failed += queue.get()

    return num_failed

def run_vtr_flow_process(queue, run_dirs, job):
    work_dir = job.work_dir(run_dirs[job.task_name()])
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    log_filepath = str(PurePath(work_dir) / "vtr_flow.log")
    out = None
    vtr_flow_out = str(PurePath(work_dir) / "vtr_flow.out")
    with open(log_filepath, 'w+') as log_file:
        with open(vtr_flow_out, 'w+') as out_file:
            with redirect_stdout(out_file):
                out = run_vtr_flow(job.run_command(), find_vtr_file("run_vtr_flow.py"))
        with open(vtr_flow_out, "r") as out_file:
            for line in out_file.readlines():
                print(line,end="")
    if out:
        queue.put(1)
    else:
        queue.put(0)

def print_log(log_file, indent="    "):
    #Save position
    curr_pos = log_file.tell()

    log_file.seek(0) #Rewind to start

    #Print log
    for line in log_file:
        line = line.rstrip()
        print (indent + line)
    print ("")

    #Return to original position
    log_file.seek(curr_pos)


def resolve_vtr_source_file(config, filename, base_dir=""):
    """
    Resolves an filename with a base_dir

    Checks the following in order:
        1) filename as absolute path
        2) filename under config directory
        3) base_dir as absolute path (join filename with base_dir)
        4) filename and base_dir are relative paths (join under vtr_root)
    """
    
    #Absolute path
    if PurePath(filename).is_absolute():
        return filename

    #Under config
    config_path = Path(config.config_dir)
    assert config_path.is_absolute()
    joined_path = config_path / filename
    if joined_path.exists():
        return str(joined_path)

    #Under base dir
    base_path = Path(base_dir)
    if base_path.is_absolute():
        #Absolute base
        joined_path = base_path / filename
        if joined_path.exists():
            return str(joined_path)
    else:
        #Relative base under the VTR flow directory
        joined_path = Path(find_vtr_root()) / 'vtr_flow' / base_dir / filename
        if joined_path.exists():
            return str(joined_path)

    #Not found
    raise InspectError("Failed to resolve VTR source file {}".format(filename))

def parse_tasks(args, configs, jobs):
    """
    Parse the selection of tasks specified in configs and associated jobs
    """
    for config in configs:
        config_jobs = [job for job in jobs if job.task_name() == config.task_name]
        parse_task(args, config, config_jobs)

def parse_task(args, config, config_jobs, flow_metrics_basename="parse_results.txt"):
    """
    Parse a single task run.

    This generates a file parse_results.txt in the task's working directory,
    which is an amalgam of the parse_rests.txt's produced by each job (flow invocation)
    """
    run_dir = find_latest_run_dir(args, config)
    
    print_verbose(BASIC_VERBOSITY, args.verbosity, "Parsing task run {}".format(run_dir))

    #Record max widths for pretty printing
    max_arch_len = len("architecture")
    max_circuit_len = len("circuit")
    for job in config_jobs:
        work_dir = job.work_dir(get_latest_run_dir(find_task_dir(args, config)))
        if job.parse_command():
                        parse_filepath = str(PurePath(work_dir) / flow_metrics_basename)
                        with open(parse_filepath, 'w+') as parse_file:
                            with redirect_stdout(parse_file):
                                parse_vtr_flow(job.parse_command())
        if job.second_parse_command():
                        parse_filepath = str(PurePath(work_dir) / "parse_results_2.txt")
                        with open(parse_filepath, 'w+') as parse_file:
                            with redirect_stdout(parse_file):
                                parse_vtr_flow(job.second_parse_command())
        if job.qor_parse_command():
                        parse_filepath = str(PurePath(work_dir) / "qor_results.txt")
                        with open(parse_filepath, 'w+') as parse_file:
                            with redirect_stdout(parse_file):
                                parse_vtr_flow(job.qor_parse_command())
        max_arch_len = max(max_arch_len, len(job.arch()))
        max_circuit_len = max(max_circuit_len, len(job.circuit()))
    parse_files(config_jobs,run_dir,flow_metrics_basename)

    if config.second_parse_file:
        parse_files(config_jobs,run_dir,"parse_results_2.txt")

    if config.qor_parse_file:
        parse_files(config_jobs,run_dir,"qor_results.txt")
        
    
def parse_files(config_jobs, run_dir, flow_metrics_basename="parse_results.txt"):
    task_parse_results_filepath = str(PurePath(run_dir) / flow_metrics_basename)
    with open(task_parse_results_filepath, "w") as out_f:

        #Start the header
        
        header = True
        for job in config_jobs:
            #Open the job results file
            #
            #The job results file is basically the same format, but excludes the architecture and circuit fields,
            #which we prefix to each line of the task result file
            job_parse_results_filepath = Path(job.work_dir(run_dir)) /  flow_metrics_basename
            if job_parse_results_filepath.exists():
                with open(job_parse_results_filepath) as in_f:
                    lines = in_f.readlines()
                    assert len(lines) == 2
                    if header:
                        #First line is the header
                        print(lines[0],file=out_f, end="")
                        header = False
                    #Second line is the data
                    print(lines[1], file = out_f, end="")
            else:
                print_verbose(BASIC_VERBOSITY, args.verbosity, "Warning: Flow result file not found (task QoR will be incomplete): {} ".format(str(job_parse_results_filepath)))

if __name__ == "__main__":
    main()
