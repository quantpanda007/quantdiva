/**
 * Commodity Spot Avg Option — instrument module (placeholder)
 *
 * TODO: Add fieldGroups for grouped 3-column layout when needed.
 * Currently uses flat FIELDS from schema_master.js.
 */

const commodity_spot_avg_option = {

  fieldGroups: null,  // null = use flat FIELDS fallback

  flatFields: null,   // null = use FIELDS['commodity_spot_avg_option'] from schema_master

  apiType: 'commodity_spot_avg_option',

  mapPayload: null,   // null = use default collectPayload logic

  bulkUpload: false,

  onFieldChange: null,
};

INSTRUMENT_REGISTRY['commodity_spot_avg_option'] = commodity_spot_avg_option;
