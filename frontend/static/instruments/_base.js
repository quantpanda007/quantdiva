/**
 * Shared field blocks and metadata keys for instrument modules.
 * Instruments import and spread these into their FIELD_GROUPS.
 */

// ─── Counterparty block (common to all grouped instruments) ───
const COUNTERPARTY_FIELDS = [
  {id:'optima_id',label:'Optima ID',type:'text',val:'',ph:'Auto-generated',ro:true},
  {id:'client_name',label:'Client Name',type:'text',val:'',ph:'e.g. EXL India'},
  {id:'transaction_ref',label:'Transaction Ref No.',type:'text',val:'',ph:'e.g. L01SFWD000130'},
];

const COUNTERPARTY_A = [
  {sub:'Counterparty A'},
  {id:'cpty_a_name',label:'Name',type:'text',val:''},
  {id:'cpty_a_direction',label:'Direction',type:'select',opts:['Buy','Sell'],val:'Buy'},
];

const COUNTERPARTY_B = [
  {sub:'Counterparty B'},
  {id:'cpty_b_name',label:'Name',type:'text',val:''},
  {id:'cpty_b_direction',label:'Direction',type:'select',opts:['Buy','Sell'],val:'Sell'},
];

// ─── FX Notional blocks ───
const FX_NOTIONAL_1 = [
  {sub:'Notional Currency 1'},
  {id:'notional_1_position',label:'Position',type:'select',opts:['Buy','Sell'],val:'Sell'},
  {id:'notional_1_ccy',label:'Currency',type:'select',opts:['INR','USD','EUR','GBP','JPY'],val:'INR'},
  {id:'notional_1_amount',label:'Amount',type:'number',val:10000000,ph:'e.g. 10,00,000'},
];

const FX_NOTIONAL_2 = [
  {sub:'Notional Currency 2'},
  {id:'notional_2_position',label:'Position',type:'select',opts:['Buy','Sell'],val:'Buy'},
  {id:'notional_2_ccy',label:'Currency',type:'select',opts:['INR','USD','EUR','GBP','JPY'],val:'USD'},
  {id:'notional_2_amount',label:'Amount',type:'number',val:0,ph:'Derived from CCY1'},
];

// ─── FX Market Data block ───
const FX_MARKET_DATA = [
  {id:'spot',label:'Spot',type:'number',val:85.47,ph:'e.g. 85.47'},
  {id:'rate',label:'Domestic Rate',type:'number',val:0.065,ph:'e.g. 0.065'},
  {id:'foreign_rate',label:'Foreign Rate',type:'number',val:0.045,ph:'e.g. 0.045'},
  {id:'forward_curve',label:'Forward Curve',type:'text',val:'INR.MIFOR',ph:'Curve name'},
  {id:'forward_rate',label:'Forward Rate',type:'number',val:0,ph:'Computed'},
  {id:'discount_curve',label:'Discount Curve',type:'text',val:'INR.OIS',ph:'Curve name'},
  {id:'discount_factor',label:'Discount Factor',type:'number',val:0,ph:'Computed'},
  {id:'premium',label:'Premium',type:'number',val:0,ph:'0 for forwards'},
];

// ─── Currency pair selector ───
const CCY_PAIR_FIELD = {id:'ccy_pair',label:'Currency Pair',type:'select',opts:['USDINR','EURINR','GBPINR','EURUSD','GBPUSD','USDJPY'],val:'USDINR'};

// ─── Base date fields ───
const BASE_DATES = [
  {id:'transaction_date',label:'Transaction Date',type:'date',val:''},
  {id:'effective_date',label:'Effective Date',type:'date',val:''},
  {id:'reporting_date',label:'Valuation / Reporting Date',type:'date',val:''},
];

// ─── Metadata keys (not sent to pricing engine) ───
const METADATA_KEYS = new Set([
  'optima_id', 'client_name', 'transaction_ref', 'contract_type',
  'cpty_a_name', 'cpty_a_direction', 'cpty_b_name', 'cpty_b_direction',
  'notional_1_position', 'notional_2_position',
  'notional_1_ccy', 'notional_2_ccy', 'notional_2_amount',
  'transaction_date', 'effective_date',
  'delivery_start_date', 'delivery_end_date', 'maturity_hint',
  'forward_curve', 'discount_curve', 'discount_factor', 'forward_rate',
  'premium',
]);
