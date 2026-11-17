/**
 * FX Vanilla Forward — instrument module
 *
 * Analytical pricing: NPV = N × (F - K) × DF × sign
 * No custom field logic. Direct payload mapping.
 */

const fx_forward = {

  fieldGroups: {
    columns: 4,
    groups: [
      {
        id:'counterparty', label:'Counterparty Details',
        collapsible: true, collapsed: false,
        fields: [
          ...COUNTERPARTY_FIELDS,
          {id:'contract_type',label:'Type of Contract',type:'text',val:'Forward',ro:true},
          ...COUNTERPARTY_A,
          ...COUNTERPARTY_B,
        ],
      },
      {
        id:'economic', label:'Economic Terms',
        fields: [
          {id:'strike',label:'Strike Rate',type:'number',val:86.88,ph:'Forward rate'},
          CCY_PAIR_FIELD,
          ...FX_NOTIONAL_1,
          ...FX_NOTIONAL_2,
        ],
      },
      
      {
        id:'market_data', label:'Market Data as on Valuation Date',
        fields: [...FX_MARKET_DATA],
      },
      {
        id:'dates', label:'Dates',
        fields: [
          ...BASE_DATES,
          {id:'maturity_date',label:'Maturity Date',type:'date',val:'2027-07-29'},
        ],
      },
    ],
  },

  flatFields: [
    {id:'ccy_pair',label:'Currency Pair',type:'text',val:'USDINR'},
    {id:'notional',label:'Notional',type:'number',val:1e6},
    {id:'strike',label:'Forward Rate',type:'number',val:84.50},
    {id:'expiry',label:'Maturity',type:'date',val:'2026-01-15'},
    {id:'direction',label:'Direction',type:'select',opts:['buy','sell'],val:'buy'},
  ],

  apiType: 'fx_forward',

  mapPayload(allFields) {
    return {
      strike: allFields.strike,
      ccy_pair: allFields.ccy_pair,
      notional: allFields.notional_1_amount,
      direction: (allFields.notional_1_position || 'sell').toLowerCase(),
      delivery_date: allFields.maturity_date,
      expiry: allFields.maturity_date,
    };
  },

  bulkUpload: true,
  hideModelEngine: true,

  onFieldChange(fieldId) {

    // 🔹 Attach listener ONCE (robust fix)
    if (!window.__fx_forward_bound) {
      window.__fx_forward_bound = true;

      setTimeout(() => {
        const ccy1El = document.getElementById('f-notional_1_position');
        const ccy2El = document.getElementById('f-notional_2_position');

        if (ccy1El && ccy2El) {
          ccy1El.addEventListener('change', () => {
            const val = (ccy1El.value || '').toLowerCase();
            ccy2El.value = (val === 'buy') ? 'sell' : 'buy';
          });
        }
      }, 0);
    }

    // 🔹 EXISTING LOGIC (UNCHANGED)
    const triggerFields = [
      'transaction_ref','cpty_a_name','cpty_b_name',
      'notional_1_amount','strike','ccy_pair','transaction_date',
    ];

    if (!triggerFields.includes(fieldId)) return;

    const g = (id) => {
      const el = document.getElementById('f-' + id);
      return el ? el.value : '';
    };

    const id = generateOptimaId({
      asset:           'FWD',
      ccy_pair:        g('ccy_pair'),
      transaction_ref: g('transaction_ref'),
      trade_date:      g('transaction_date'),
      cpty_a:          g('cpty_a_name'),
      cpty_b:          g('cpty_b_name'),
      notional:        g('notional_1_amount'),
      strike:          g('strike'),
    });

    const el = document.getElementById('f-optima_id');
    if (el) el.value = id;
  },
};

INSTRUMENT_REGISTRY['fx_forward'] = fx_forward;
