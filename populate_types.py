#!/usr/bin/env python
# This is a script intended to be ran only when there are updates to the item
# database. The results are dumped into a file as JSON to be read by the app.
#
# This script requires an installed (and updated) copy of Eve Online. This
# requires Reverence, a tool which looks at the game cache to get up-to-date
# data. URL: https://github.com/ntt/reverence/

import json
from reverence import blue


if __name__ == '__main__':

    # EVEPATH = '/Applications/EVE Online.app/Contents/Resources/EVE Online.app/Contents/Resources/transgaming/c_drive/Program Files/CCP/EVE'
    EVEPATH = "C:\Program Files (x86)\CCP\EVE"

    eve = blue.EVE(EVEPATH)
    cfg = eve.getconfigmgr()

    all_types = {}
    for (typeID, groupID, typeName, marketGroupID, volume, capacity) in \
            cfg.invtypes.Select('typeID', 'groupID', 'typeName',
                'marketGroupID', 'volume', 'capacity'):

        hasMarket = marketGroupID is not None
        if not hasMarket:
            # since the app only deals with market items, do not include things like suns
            continue
        
        print("Populating info for: %s" % typeName)
        
        slot = None
        for row in cfg.dgmtypeeffects[typeID]:
            if row.effectID in [11, 12, 13, 2663]:
                slot = cfg.dgmeffects.Get(row.effectID).effectName

        d = {
                'typeID': typeID,
                'groupID': groupID,
                'typeName': typeName,
                'volume': volume,
                'capacity': capacity,
                'market': hasMarket,
                'slot': slot
            }

        # super, carrier, titan, dread
        if groupID in [659, 547, 30, 485] and typeID in cfg.invtypematerials:
            components = []
            for typeID, materialTypeID, component_quantity in cfg.invtypematerials[typeID]:
                components.append({
                                    'typeID': typeID,
                                    'materialTypeID': materialTypeID,
                                    'quantity': component_quantity,
                                })

            d['components'] = components
        name_lower = typeName.lower()
        all_types[name_lower] = d
        # Create a stub for blueprint copies
        if name_lower.endswith(' blueprint'):
            copy_name = typeName + ' (Copy)'
            all_types[copy_name.lower()] = {
                'typeID': typeID,
                'groupID': groupID,
                'typeName': copy_name,
                'volume': volume,
                'capacity': capacity,
                'market': False,
            }

    with open('types.json', 'w') as f:
        f.write(json.dumps(all_types, indent=2))
