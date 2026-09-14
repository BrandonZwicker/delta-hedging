def contracts_to_hedge(num_shares, option_delta,shares_per_contract=100):

    #Safeguard if the option delta is zero
    if option_delta == 0:
        raise ValueError("option_delta is zero — this option hedges nothing")

    position_delta = num_shares
    contract_delta = shares_per_contract * option_delta
    contracts = -position_delta / contract_delta

    return contracts