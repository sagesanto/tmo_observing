import sys

def challenge(condition, msg, override=False):
    if condition or override:
        return
    resp = input(f"{msg} Type 'yes' to confirm:")
    if resp.lower.strip() != 'yes':
        print('No confirmation. Exiting.')
        sys.exit(1)