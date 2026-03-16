/**
 * FX Range Forward — instrument module
 *
 * Same pricing as vanilla forward, but with delivery date window.
 * Auto-computes maturity: Sell → start date, Buy → end date.
 * Maps to fx_forward on the backend.
 */
const fx_range_forward = {
  fieldGroups: {
    columns: 4,
    groups: [
      {
        id:'counterparty', label:'Counterparty Details',
        collapsible: true, collapsed: true,
        fields: [
          ...COUNTERPARTY_FIELDS,
          {id:'contract_type',label:'Type of Contract',type:'text',val:'Range Forward',ro:true},
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
          {sub:'Delivery Window'},
          {id:'delivery_start_date',label:'Delivery Start Date',type:'date',val:'',ph:'From date'},
          {id:'delivery_end_date',label:'Delivery End Date',type:'date',val:'',ph:'To date'},
          {sub:'Computed Maturity'},
          {id:'maturity_date',label:'Maturity Date',type:'date',val:'',ph:'Auto-computed from direction'},
          {id:'maturity_hint',label:'',type:'hint',val:'Sell → start date, Buy → end date'},
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
    {id:'strike',label:'Strike Rate',type:'number',val:86.88},
    {id:'expiry',label:'Maturity Date',type:'date',val:'2026-01-15'},
    {id:'direction',label:'Direction',type:'select',opts:['buy','sell'],val:'sell'},
  ],
  apiType: 'fx_forward',  // same backend as vanilla forward
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
  // Auto-compute maturity from delivery window + direction
  onFieldChange(fieldId) {
    // Generate Optima ID when deal inputs change
    const idTriggers = [
      'transaction_ref','cpty_a_name','cpty_b_name',
      'notional_1_amount','strike','ccy_pair','transaction_date',
    ];
    if (idTriggers.includes(fieldId)) {
      const g = (id) => { const el = document.getElementById('f-' + id); return el ? el.value : ''; };
      const id = generateOptimaId({
        asset:           'RFW',
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
    }

    // Maturity resolution
    if (['delivery_start_date','delivery_end_date','notional_1_position'].includes(fieldId)) {
      const startEl = document.getElementById('f-delivery_start_date');
      const endEl = document.getElementById('f-delivery_end_date');
      const posEl = document.getElementById('f-notional_1_position');
      const matEl = document.getElementById('f-maturity_date');
      const hintEl = document.getElementById('f-maturity_hint');
      if (!startEl || !endEl || !posEl || !matEl) return;
      const start = startEl.value;
      const end = endEl.value;
      const position = posEl.value.toLowerCase();
      if (!start && !end) return;
      let maturity = '';
      let hintText = '';
      if (position === 'sell') {
        maturity = start || end;
        hintText = 'Auto: delivery start date (Sell → earliest)';
      } else {
        maturity = end || start;
        hintText = 'Auto: delivery end date (Buy → latest)';
      }
      matEl.value = maturity;
      if (hintEl) hintEl.textContent = hintText;
    }
  },
};
INSTRUMENT_REGISTRY['fx_range_forward'] = fx_range_forward;
