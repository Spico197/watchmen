import argparse
import random
import string
import sys

from watchmen import WatchClient


def parse_args(in_args=None):
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--task_name", type=str, required=True, help="Take Name")
    arg_parser.add_argument("--cuda", type=str, required=True, help="cuda to be waited")
    arg_parser.add_argument(
        "--req_gpu_num",
        type=int,
        required=False,
        default=1,
        help="request number of gpus",
    )
    arg_parser.add_argument(
        "--wait",
        choices=["schedule", "queue", "none"],
        default="none",
        help="scheduling/queue wait",
    )
    arg_parser.add_argument(
        "--token",
        type=str,
        default="",
        help="authentication token",
    )
    arg_parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="host",
    )
    arg_parser.add_argument(
        "--port",
        type=int,
        default=62333,
        help="port",
    )
    arg_info = arg_parser.parse_args(args=in_args)
    return arg_info


if __name__ == "__main__":
    in_argv = parse_args()
    if in_argv.wait == "none":
        sys.exit(0)
    random_id = "-" + "".join(random.sample(string.ascii_letters + string.digits, 8))
    exp_id = in_argv.task_name + random_id
    watch_client = WatchClient(
        id=exp_id,
        gpus=eval(f"[{in_argv.cuda}]"),
        server_host=in_argv.host,
        server_port=in_argv.port,
        req_gpu_num=in_argv.req_gpu_num,
        mode=in_argv.wait,
        timeout=60,
        token=in_argv.token,
    )
    available_gpus = watch_client.wait()
    available_gpus = [str(x) for x in available_gpus]
    print(",".join(available_gpus), end="")
