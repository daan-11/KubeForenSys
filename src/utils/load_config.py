import argparse

def parse_args():
    parser = argparse.ArgumentParser(description="A tool to collect Kubernetes data and push it to a Log Analytics workspace in Azure")
    parser.add_argument("--since_seconds", type=int, help="Fetch logs since these many seconds ago (default: 86400)")
    parser.add_argument("--workspace_name", type=str, help="Name of the Log Analytics workspace (default: 'KubeForenSys-LAW')")
    parser.add_argument("--dce_name", type=str, help="Name of the Data Collection Endpoint (default: 'Kube-DCE')")
    parser.add_argument("--location", type=str, help="Azure region (default: 'west-europe')")
    parser.add_argument("--continuous", action="store_true", help="Run continuously instead of just once")
    parser.add_argument("--interval", type=int, default=60, help="Interval in seconds between runs when --continuous is set (default: 60)")
    parser.add_argument("--initial", action="store_true", help="If set, create LAW, DCE, DCR, and tables, then exit.")

    args = parser.parse_args()

    return {k: v for k, v in vars(args).items() if v is not None}