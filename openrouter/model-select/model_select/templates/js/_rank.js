function bucketBounds(value, minimum, step) {
  var stepsAboveMinimum = Math.floor((value - minimum) / step);
  var low = minimum + stepsAboveMinimum * step;
  return [low, low + step];
}

function groupByBucket(items, metricOf, minimum, step) {
  var buckets = new Map();
  items.forEach(function (item) {
    var metric = metricOf(item);
    if (metric < minimum) {
      return;
    }
    var bounds = bucketBounds(metric, minimum, step);
    var key = bounds[0] + "," + bounds[1];
    if (!buckets.has(key)) {
      buckets.set(key, { low: bounds[0], high: bounds[1], items: [] });
    }
    buckets.get(key).items.push(item);
  });
  return buckets;
}

function filterParetoFrontier(items, priceOf, metricOf) {
  var result = [];
  items.forEach(function (candidate) {
    var candidatePrice = priceOf(candidate);
    var candidateMetric = metricOf(candidate);
    var dominated = false;
    for (var i = 0; i < items.length; i++) {
      var other = items[i];
      if (other === candidate) {
        continue;
      }
      var otherPrice = priceOf(other);
      var otherMetric = metricOf(other);
      var notWorse = otherPrice <= candidatePrice && otherMetric >= candidateMetric;
      var strictlyBetter = otherPrice < candidatePrice || otherMetric > candidateMetric;
      if (notWorse && strictlyBetter) {
        dominated = true;
        break;
      }
    }
    if (!dominated) {
      result.push(candidate);
    }
  });
  return result;
}

function codingIndexOf(record) {
  return record.coding_index;
}

function buildAxisView(buckets, priceField, paretoOnly) {
  function priceOf(record) {
    return record[priceField];
  }
  var view = [];
  buckets.forEach(function (bucket) {
    var items = paretoOnly
      ? filterParetoFrontier(bucket.items, priceOf, codingIndexOf)
      : bucket.items.slice();
    var rows = items.map(function (record) {
      return {
        id: record.id,
        name: record.name,
        coding_index: record.coding_index,
        price_per_million: priceOf(record),
      };
    });
    rows.sort(function (a, b) {
      return a.price_per_million - b.price_per_million;
    });
    if (rows.length > 0) {
      view.push({ low: bucket.low, high: bucket.high, rows: rows });
    }
  });
  view.sort(function (a, b) {
    return a.low - b.low;
  });
  return view;
}
