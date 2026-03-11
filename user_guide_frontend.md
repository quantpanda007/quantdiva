static/
├── optima.html              ← same UI, updated script tags
├── optima_core.js           ← shared logic (1330 lines, was 1367)
├── optima_registry.js       ← registry verification
├── schema/
│   └── schema_master.js     ← SCHEMA, MODULE_TABS, ASSET_CLASSES, etc. (486 lines)
└── instruments/
    ├── _base.js             ← shared field blocks (72 lines)
    ├── fx/
    │   ├── fx_forward.js        ← COMPLETE: fieldGroups + mapPayload
    │   ├── fx_range_forward.js  ← COMPLETE: fieldGroups + onFieldChange + apiType mapping
    │   ├── fx_option.js         ← placeholder
    │   ├── fx_seagull.js        ← placeholder
    │   ├── fx_call_spread.js    ← placeholder
    │   ├── fx_put_spread.js     ← placeholder
    │   ├── fx_range_forward_opt.js ← placeholder
    │   ├── principal_only_swap.js  ← placeholder
    │   ├── ccirs.js             ← placeholder
    │   ├── fx_swaption.js       ← placeholder
    │   ├── fx_digital.js        ← placeholder
    │   └── fx_barrier.js        ← placeholder
    ├── rates/ (8 placeholders)
    ├── equity/ (7 placeholders)
    ├── commodity/ (4 placeholders)
    └── credit/ (1 placeholder)




How It Works

schema_master.js loads first — creates INSTRUMENT_REGISTRY = {}
_base.js loads — defines shared field blocks (COUNTERPARTY_FIELDS, FX_MARKET_DATA, METADATA_KEYS)
Each instrument file loads — registers itself: INSTRUMENT_REGISTRY['fx_forward'] = { fieldGroups, mapPayload, ... }
optima_registry.js loads — verifies all SCHEMA instruments have a registry entry
optima_core.js loads — uses registry for everything: field groups, payload mapping, field change handlers, bulk upload support, API type mapping