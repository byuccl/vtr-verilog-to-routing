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
from contextlib import redirect_stdout
from prettytable import PrettyTable
from vtr import load_list_file, find_vtr_file, print_verbose, find_vtr_root, CommandRunner, format_elapsed_time, RawDefaultHelpFormatter, argparse_str2bool, get_next_run_dir, get_latest_run_dir, load_task_config, TaskConfig, find_task_config_file, CommandRunner, load_pass_requirements, load_parse_results, parse_vtr_flow, load_script_param, get_latest_run_number, pretty_print_table

def main():
    vtr_command_main(sys.argv[1:])

def vtr_command_main(arg_list, prog = None):
    print("test")

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
                pretty_print_table(job_parse_results_filepath)
            else:
                print_verbose(BASIC_VERBOSITY, args.verbosity, "Warning: Flow result file not found (task QoR will be incomplete): {} ".format(str(job_parse_results_filepath)))
def find_latest_run_dir(args, config):
    task_dir = find_task_dir(args, config)

    run_dir = get_latest_run_dir(task_dir)

    if not run_dir:
        raise InspectError("Failed to find run directory for task '{}' in '{}'".format(config.task_name, task_dir))

    assert Path(run_dir).is_dir()

    return run_dir

def find_task_dir(args, config):
    task_dir = None
    #Task dir is just above the config directory
    task_dir = Path(config.config_dir).parent
    assert task_dir.is_dir

    return str(task_dir)
    
if __name__ == "__main__":
    main()