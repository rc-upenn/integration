from web3 import Web3
from web3.providers.rpc import HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware #Necessary for POA chains
from datetime import datetime
import json
import pandas as pd


def connect_to(chain):
    if chain == 'source':  # The source contract chain is avax
        api_url = f"https://api.avax-test.network/ext/bc/C/rpc" #AVAX C-chain testnet

    if chain == 'destination':  # The destination contract chain is bsc
        api_url = f"https://data-seed-prebsc-1-s1.binance.org:8545/" #BSC testnet

    if chain in ['source','destination']:
        w3 = Web3(Web3.HTTPProvider(api_url))
        # inject the poa compatibility middleware to the innermost layer
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def get_contract_info(chain, contract_info):
    """
        Load the contract_info file into a dictionary
        This function is used by the autograder and will likely be useful to you
    """
    try:
        with open(contract_info, 'r')  as f:
            contracts = json.load(f)
    except Exception as e:
        print( f"Failed to read contract info\nPlease contact your instructor\n{e}" )
        return 0
    return contracts[chain]



def scan_blocks(chain, contract_info="contract_info.json"):
    """
        chain - (string) should be either "source" or "destination"
        Scan the last 5 blocks of the source and destination chains
        Look for 'Deposit' events on the source chain and 'Unwrap' events on the destination chain
        When Deposit events are found on the source chain, call the 'wrap' function the destination chain
        When Unwrap events are found on the destination chain, call the 'withdraw' function on the source chain
    """

    # This is different from Bridge IV where chain was "avax" or "bsc"
    if chain not in ['source','destination']:
        print( f"Invalid chain: {chain}" )
        return 0
    
        #YOUR CODE HERE
    with open(contract_info, 'r') as f:
        raw = json.load(f)
    warden_key = raw.get('warden_private_key') or raw.get('private_key')
    if warden_key is None:
        print("Warden private key not found in contract_info.json")
        return 0
 
    w3_source = connect_to('source')
    w3_destination = connect_to('destination')
 
    source_info = get_contract_info('source', contract_info)
    destination_info = get_contract_info('destination', contract_info)
    if source_info == 0 or destination_info == 0:
        return 0
 
    source_address = Web3.to_checksum_address(source_info['address'])
    destination_address = Web3.to_checksum_address(destination_info['address'])
    source_contract = w3_source.eth.contract(address=source_address, abi=source_info['abi'])
    destination_contract = w3_destination.eth.contract(address=destination_address, abi=destination_info['abi'])
 
    warden = w3_source.eth.account.from_key(warden_key)
    warden_address = warden.address
 
    if chain == 'source':
        w3_read = w3_source
        read_contract = source_contract
        event_obj = read_contract.events.Deposit
        w3_write = w3_destination
        write_contract = destination_contract
    else:
        w3_read = w3_destination
        read_contract = destination_contract
        event_obj = read_contract.events.Unwrap
        w3_write = w3_source
        write_contract = source_contract
 
    latest = w3_read.eth.block_number
    from_block = max(0, latest - 5)
    to_block = latest
 
    try:
        events = event_obj().get_logs(from_block=from_block, to_block=to_block)
    except Exception as e:
        print(f"Failed to fetch events: {e}")
        return 0
 
    for ev in events:
        args = ev['args']
        if chain == 'source':
            token = Web3.to_checksum_address(args['token'])
            recipient = Web3.to_checksum_address(args['recipient'])
            amount = args['amount']
            fn = write_contract.functions.wrap(token, recipient, amount)
        else:
            underlying = Web3.to_checksum_address(args.get('underlying_token') or args.get('token'))
            to_addr = Web3.to_checksum_address(args.get('to') or args.get('recipient'))
            amount = args['amount']
            fn = write_contract.functions.withdraw(underlying, to_addr, amount)
 
        try:
            nonce = w3_write.eth.get_transaction_count(warden_address, 'pending')
            try:
                gas_limit = int(fn.estimate_gas({'from': warden_address}) * 1.3)
            except Exception:
                gas_limit = 500000
            tx = fn.build_transaction({
                'from': warden_address,
                'nonce': nonce,
                'gas': gas_limit,
                'gasPrice': w3_write.eth.gas_price,
                'chainId': w3_write.eth.chain_id,
            })
            signed = w3_write.eth.account.sign_transaction(tx, private_key=warden_key)
            raw_tx = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction', None)
            tx_hash = w3_write.eth.send_raw_transaction(raw_tx)
            w3_write.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            print(f"Sent tx {tx_hash.hex()}")
        except Exception as e:
            print(f"Transaction failed (likely duplicate or revert): {e}")
            continue
 
    return 1
