import sys
import argparse

import torch

from watchmen import WatchClient
from watchmen.client import ClientMode


def main():
    # Training settings
    parser = argparse.ArgumentParser(description='Minimal GPU Scheduling Example')
    parser.add_argument("--id", type=str, default="id",
                        help="identifier")
    parser.add_argument("--cuda", type=str, default="0",
                        help="cuda devices, seperated by `,` with no spaces")
    parser.add_argument("--wait", action="store_true",
                        help="wait for watchmen signal")
    parser.add_argument("--wait_mode", type=str,
                        choices=["queue", "schedule"], default="queue",
                        help="gpu waiting mode")
    parser.add_argument("--req_gpu_num", type=int, default=1,
                        help="number of GPUs to request")
    parser.add_argument("--token", type=str, default="",
                        help="authentication token")
    args = parser.parse_args()

    """WATCHMEN"""
    if args.wait:
        if args.wait_mode == 'queue':
            waiting_mode = ClientMode.QUEUE
        else:
            waiting_mode = ClientMode.SCHEDULE
        client = WatchClient(id=f"mnist single card {args.id} cuda={args.cuda}",
                             gpus=eval(f"[{args.cuda}]"),
                             req_gpu_num=args.req_gpu_num, mode=waiting_mode,
                             server_host="127.0.0.1", server_port=62333,
                             token=args.token)
        # client.register()
        available_gpus = []
        available_gpus = client.wait()
        if len(available_gpus) <= 0:
            sys.exit(1)
        else:
            device = torch.device(f"cuda:{available_gpus[0]}")
    """END OF WATCHMEN"""
    print(f"Using GPU: {device}")
    input("Press Enter to continue...")


if __name__ == '__main__':
    main()
