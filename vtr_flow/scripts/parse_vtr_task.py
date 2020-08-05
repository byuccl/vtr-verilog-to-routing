def parse_tasks(args, configs, jobs):
    """
    Parse the selection of tasks specified in configs and associated jobs
    """
    for config in configs:
        config_jobs = [job for job in jobs if job.task_name() == config.task_name]
        parse_task(args, config, config_jobs)

def parse_task(args, config, config_jobs, task_metrics_filepath=None, flow_metrics_basename="parse_results.txt"):
    """
    Parse a single task run.

    This generates a file parse_results.txt in the task's working directory,
    which is an amalgam of the parse_rests.txt's produced by each job (flow invocation)
    """
    run_dir = find_latest_run_dir(args, config)

    print_verbose(BASIC_VERBOSITY, args.verbosity, "Parsing task run {}".format(run_dir))

    for job in config_jobs:
        #Re-run parsing only
        cmd = job.parse_command()
        cmd += ['-v', str(max(0, args.verbosity-3))]
        subprocess.check_call(cmd, cwd=job.work_dir(run_dir))

    if task_metrics_filepath is None:
        task_metrics_filepath = task_parse_results_filepath = str(PurePath(run_dir).joinpath("parse_results.txt"))

    #Record max widths for pretty printing
    max_arch_len = len("architecture")
    max_circuit_len = len("circuit")
    for job in config_jobs:
        max_arch_len = max(max_arch_len, len(job.arch()))
        max_circuit_len = max(max_circuit_len, len(job.circuit()))

    with open(task_parse_results_filepath, "w") as out_f:

        #Start the header
        print >>out_f, "{:<{arch_width}}\t{:<{circuit_width}}\t".format("architecture", "circuit", arch_width=max_arch_len, circuit_width=max_circuit_len),
        header = True

        for job in config_jobs:
            #Open the job results file
            #
            #The job results file is basically the same format, but excludes the architecture and circuit fields,
            #which we prefix to each line of the task result file
            job_parse_results_filepath = Path(run_dir) / job.arch / job.circuit / flow_metrics_basename
            if job_parse_results_filepath.exists:
                with job_parse_results_filepath.open() as in_f:
                    lines = in_f.readlines()

                    assert len(lines) == 2

                    if header:
                        #First line is the header
                        print >>out_f, lines[0],
                        header = False

                    #Second line is the data
                    print >>out_f, "{:<{arch_width}}\t{:<{circuit_width}}\t{}".format(job.arch(), job.circuit(), lines[1], arch_width=max_arch_len, circuit_width=max_circuit_len),
            else:
                print_verbose(BASIC_VERBOSITY, args.verbosity, "Warning: Flow result file not found (task QoR will be incomplete): {} ".format(str(job_parse_results_filepath)))
