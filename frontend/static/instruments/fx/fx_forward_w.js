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
        id:'dates', label:'Dates',
        fields: [
          ...BASE_DATES,
          {id:'maturity_date',label:'Maturity Date',type:'date',val:'2025-07-29'},
        ],
      },
      {
        id:'market_data', label:'Market Data as on Valuation Date',
        fields: [...FX_MARKET_DATA],
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

  onFieldChange: null,
};

INSTRUMENT_REGISTRY['fx_forward'] = fx_forward;
