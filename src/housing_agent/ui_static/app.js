const state = {
  payload: {},
  transcript: [],
};

const chatLog = document.querySelector("#chatLog");
const chatForm = document.querySelector("#chatForm");
const messageInput = document.querySelector("#messageInput");
const stateLabel = document.querySelector("#stateLabel");
const resetButton = document.querySelector("#resetButton");
const runButton = document.querySelector("#runButton");
const cancelButton = document.querySelector("#cancelButton");
const jsonButton = document.querySelector("#jsonButton");
const jsonDialog = document.querySelector("#jsonDialog");
const closeJsonButton = document.querySelector("#closeJsonButton");
const jsonOutput = document.querySelector("#jsonOutput");
const jsonInline = document.querySelector("#jsonInline");

const summaryPanel = document.querySelector("#summaryPanel");
const debugMessagePanel = document.querySelector("#debugMessagePanel");
const intentPanel = document.querySelector("#intentPanel");
const readinessPanel = document.querySelector("#readinessPanel");
const planPanel = document.querySelector("#planPanel");
const executionPanel = document.querySelector("#executionPanel");
const listingsPanel = document.querySelector("#listingsPanel");
const artifactsPanel = document.querySelector("#artifactsPanel");

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) return;
  messageInput.value = "";
  appendMessage("user", message);
  await sendMessage(message);
});

messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

runButton.addEventListener("click", async () => {
  appendMessage("user", "yes");
  await sendMessage("yes");
});

cancelButton.addEventListener("click", async () => {
  appendMessage("user", "no");
  await sendMessage("no");
});

resetButton.addEventListener("click", async () => {
  const response = await fetch("/api/reset", { method: "POST" });
  const data = await response.json();
  state.transcript = [];
  chatLog.replaceChildren();
  handleResponse(data);
});

jsonButton.addEventListener("click", () => {
  jsonOutput.textContent = JSON.stringify(state.payload || {}, null, 2);
  jsonDialog.showModal();
});

closeJsonButton.addEventListener("click", () => {
  jsonDialog.close();
});

async function sendMessage(message) {
  setBusy(true);
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Request failed");
    }
    handleResponse(data);
  } catch (error) {
    appendMessage("agent", `UI request failed: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

function handleResponse(data) {
  const turn = data.turn || {};
  state.payload = data.payload || {};
  state.debugMessage = turn.debug_message || "";
  stateLabel.textContent = labelForState(turn.state || state.payload.state || "collecting");
  runButton.disabled = !state.payload.pending_execution_confirmation;
  cancelButton.disabled = !state.payload.pending_execution_confirmation;
  if (turn.message) appendMessage("agent", turn.message);
  renderAll();
}

function setBusy(isBusy) {
  chatForm.querySelector("button").disabled = isBusy;
  messageInput.disabled = isBusy;
}

function appendMessage(role, text) {
  const message = document.createElement("div");
  message.className = `message ${role}`;
  message.textContent = text;
  chatLog.append(message);
  chatLog.scrollTop = chatLog.scrollHeight;
}

function renderAll() {
  renderSummary(state.payload);
  renderDebugMessage(state.debugMessage);
  renderIntent(state.payload.intent);
  renderReadiness(state.payload.search_readiness);
  renderPlan(state.payload.query_plan);
  renderExecution(state.payload.execution_result);
  renderListings(state.payload);
  renderArtifacts(state.payload.execution_result);
  renderInlineJson(state.payload);
}

function renderSummary(payload) {
  const intent = payload.intent;
  const execution = payload.execution_result;
  if (!intent) {
    setMuted(summaryPanel, "Tell me what you need, then I will ask only the next useful question.");
    return;
  }
  summaryPanel.classList.remove("muted");
  const wrapper = document.createElement("div");
  const headline = document.createElement("p");
  headline.textContent = summaryText(intent, execution);
  wrapper.append(headline);
  const facts = [
    intent.location,
    priceRange(intent),
    intent.bedrooms && `${intent.bedrooms} bedroom`,
    join(intent.type_of_places),
    join(intent.property_types),
    dateRange(intent.move_in_date, intent.move_out_date),
  ].filter(Boolean);
  if (facts.length) wrapper.append(factRow(facts));
  if (payload.pending_execution_confirmation) {
    wrapper.append(paragraph(`Ready to run. I will return up to ${payload.max_listings || 10} listings.`));
  }
  summaryPanel.replaceChildren(wrapper);
}

function renderDebugMessage(message) {
  if (!message) {
    setMuted(debugMessagePanel, "No debug message yet.");
    return;
  }
  debugMessagePanel.classList.remove("muted");
  debugMessagePanel.textContent = message;
}

function renderIntent(intent) {
  if (!intent) {
    setMuted(intentPanel, "No intent yet.");
    return;
  }
  intentPanel.classList.remove("muted");
  const entries = [
    ["Location", intent.location],
    ["Budget", priceRange(intent)],
    ["Beds", intent.bedrooms || range(intent.bedroom_min, intent.bedroom_max)],
    ["Baths", intent.bathrooms || intent.bathroom_min],
    ["Property", join(intent.property_types)],
    ["Place", join(intent.type_of_places)],
    ["Move dates", dateRange(intent.move_in_date, intent.move_out_date)],
    ["Campus", intent.campus_or_school],
    ["Furnished", intent.furnished === true ? "yes" : intent.furnished === false ? "no" : ""],
    ["Pets", join(intent.pet_policy)],
    ["Amenities", join([...(intent.required_amenities || []), ...(intent.preferred_amenities || []), ...(intent.amenities || [])])],
    ["Intent", intent.intent_kind],
  ].filter(([, value]) => hasValue(value));

  intentPanel.replaceChildren(...entries.map(([key, value]) => keyValue(key, value)));
}

function renderReadiness(readiness) {
  if (!readiness) {
    setMuted(readinessPanel, "No readiness check yet.");
    return;
  }
  readinessPanel.classList.remove("muted");
  const wrapper = document.createElement("div");
  wrapper.append(
    statusRow("Ready to search", readiness.ready_to_search ? "yes" : "no", readiness.ready_to_search ? "good" : "warn"),
    statusRow("Ready to recommend", readiness.ready_to_recommend ? "yes" : "no", readiness.ready_to_recommend ? "good" : "warn"),
    statusRow("Confidence", readiness.confidence || "unknown", "neutral")
  );
  if (readiness.reasoning_summary) wrapper.append(paragraph(readiness.reasoning_summary));
  if ((readiness.followup_questions || []).length) {
    wrapper.append(listBlock("Follow-up", readiness.followup_questions));
  }
  if ((readiness.hard_constraints || []).length) wrapper.append(listBlock("Hard constraints", readiness.hard_constraints));
  if ((readiness.soft_preferences || []).length) wrapper.append(listBlock("Soft preferences", readiness.soft_preferences));
  readinessPanel.replaceChildren(wrapper);
}

function renderPlan(queryPlan) {
  const plans = queryPlan?.provider_plans || [];
  if (!plans.length) {
    setMuted(planPanel, "No provider plan yet.");
    return;
  }
  planPanel.classList.remove("muted");
  planPanel.replaceChildren(...plans.map((plan, index) => {
    const item = document.createElement("article");
    item.className = "provider";
    const header = document.createElement("div");
    header.className = "provider-header";
    header.append(titleBlock(`${index + 1}. ${providerLabel(plan.provider)}`, join(plan.reasons) || "Provider plan"));
    header.append(badge(`${plan.quality || "unknown"} / ${plan.score ?? 0}`, plan.implemented ? "good" : "bad"));
    item.append(header);
    if (plan.search_url_preview) item.append(linkLine("Search URL", plan.search_url_preview, plan.search_url_preview));
    const app = plan.filter_application || {};
    const filters = document.createElement("div");
    filters.className = "filters";
    filters.append(
      filterBox("Source-applied", keys(app.applied_at_source)),
      filterBox("Post-filtered", keys(app.post_filters)),
      filterBox("Unsupported", keys(app.unsupported)),
      filterBox("Unknown", keys(app.unknown_unverified))
    );
    item.append(filters);
    if ((app.warnings || []).length) item.append(listBlock("Warnings", app.warnings));
    return item;
  }));
}

function renderExecution(execution) {
  if (!execution) {
    setMuted(executionPanel, "No search has run yet.");
    return;
  }
  executionPanel.classList.remove("muted");
  const providerResults = execution.provider_results || [];
  const wrapper = document.createElement("div");
  if (providerResults.length) {
    providerResults.forEach((result) => {
      const row = document.createElement("div");
      row.className = "status-row";
      row.append(titleBlock(providerLabel(result.provider), `${result.records_count || 0} listing(s)`));
      row.append(badge(result.status || "unknown", result.status === "ok" ? "good" : result.status === "failed" ? "bad" : "warn"));
      if (result.error) row.append(paragraph(result.error));
      if (result.search_url) row.append(linkLine("Search URL", result.search_url, result.search_url));
      if (result.raw_output) row.append(linkLine("Raw JSONL", artifactUrl(result.raw_output), result.raw_output));
      if (result.csv_output) row.append(linkLine("CSV", artifactUrl(result.csv_output), result.csv_output));
      wrapper.append(row);
    });
  }
  const errors = execution.errors || {};
  if (Object.keys(errors).length) wrapper.append(listBlock("Errors", Object.entries(errors).map(([key, value]) => `${key}: ${value}`)));
  executionPanel.replaceChildren(wrapper);
}

function renderListings(payload) {
  const ranking = payload.listing_ranking;
  const execution = payload.execution_result;
  const records = execution?.records || [];
  if (!records.length) {
    setMuted(listingsPanel, "No listings yet.");
    return;
  }
  listingsPanel.classList.remove("muted");
  const rankingIndex = buildRankingIndex(ranking);
  const wrapper = document.createElement("div");
  if (ranking?.overall_summary) wrapper.append(paragraph(ranking.overall_summary));
  const list = document.createElement("div");
  list.className = "cards-grid";
  list.append(...records.map((record) => recordCard(mergeRanking(record, rankingIndex))));
  wrapper.append(list);
  const unmatchedRanked = unmatchedRankedListings(ranking, records);
  if (unmatchedRanked.length) {
    const extra = document.createElement("section");
    const heading = document.createElement("h3");
    heading.textContent = "Additional ranking notes";
    extra.append(heading, ...unmatchedRanked.map((listing) => recordCard(listing)));
    wrapper.append(extra);
  }
  if ((ranking?.followup_suggestions || []).length) wrapper.append(listBlock("Useful next checks", ranking.followup_suggestions));
  listingsPanel.replaceChildren(wrapper);
}

function recordCard(record) {
  const card = document.createElement("article");
  card.className = "listing";
  const url = record.listing_url || record.detail_url || record.url || "";
  const header = document.createElement("div");
  header.className = "listing-header";
  const title = record.title || record.name || "Untitled listing";
  header.append(titleBlock(title, [record.provider || record.source, record.address || record.location].filter(Boolean).join(" / ")));
  const badges = document.createElement("div");
  badges.className = "badge-row";
  if (record.rank_bucket) badges.append(badge(bucketLabel(record.rank_bucket), bucketKind(record.rank_bucket)));
  if (record.fit_score != null) badges.append(badge(`${Math.round(Number(record.fit_score))}/100`, Number(record.fit_score) >= 75 ? "good" : "warn"));
  else if (record.coordinates_status) badges.append(badge(record.coordinates_status, record.coordinates_status === "present" ? "good" : "warn"));
  if (badges.childElementCount) header.append(badges);
  card.append(header);
  const facts = [
    record.price || record.rent,
    record.bedrooms && `${record.bedrooms} bed`,
    record.bathrooms && `${record.bathrooms} bath`,
    record.property_type,
    record.availability,
    record.square_feet,
    coordinateText(record),
  ].filter(Boolean);
  if (facts.length) card.append(factRow(facts));
  if (record.why_it_fits) card.append(paragraph(record.why_it_fits));
  if ((record.matched_constraints || []).length) card.append(listBlock("Matched", record.matched_constraints));
  if ((record.missing_info || []).length) card.append(listBlock("Missing info", record.missing_info));
  if ((record.concerns || []).length) card.append(listBlock("Concerns", record.concerns));
  if (url) card.append(linkLine("Listing", url, url));
  const images = imageValues(record.image_urls || record.images || []);
  if (images.length) card.append(imageStrip(images));
  return card;
}

function buildRankingIndex(ranking) {
  const index = new Map();
  if (!ranking) return index;
  [
    ["recommended", ranking.recommended || []],
    ["needs_verification", ranking.needs_verification || []],
    ["excluded", ranking.excluded || []],
  ].forEach(([bucket, listings]) => {
    listings.forEach((listing) => {
      const ranked = { ...listing.raw, ...listing, title: listing.title, listing_url: listing.url, rank_bucket: bucket };
      listingKeys(ranked).forEach((key) => index.set(key, ranked));
    });
  });
  return index;
}

function mergeRanking(record, rankingIndex) {
  for (const key of listingKeys(record)) {
    if (rankingIndex.has(key)) {
      return { ...record, ...rankingIndex.get(key), raw: record };
    }
  }
  return record;
}

function unmatchedRankedListings(ranking, records) {
  if (!ranking) return [];
  const recordKeys = new Set(records.flatMap((record) => listingKeys(record)));
  const ranked = [
    ...((ranking.recommended || []).map((listing) => ({ ...listing.raw, ...listing, title: listing.title, listing_url: listing.url, rank_bucket: "recommended" }))),
    ...((ranking.needs_verification || []).map((listing) => ({ ...listing.raw, ...listing, title: listing.title, listing_url: listing.url, rank_bucket: "needs_verification" }))),
    ...((ranking.excluded || []).map((listing) => ({ ...listing.raw, ...listing, title: listing.title, listing_url: listing.url, rank_bucket: "excluded" }))),
  ];
  return ranked.filter((listing) => !listingKeys(listing).some((key) => recordKeys.has(key)));
}

function listingKeys(record) {
  const keys = [];
  const url = record.listing_url || record.detail_url || record.url || "";
  if (url) keys.push(`url:${url}`);
  if (record.listing_id) keys.push(`id:${record.listing_id}`);
  const title = record.title || record.name || "";
  const provider = record.provider || record.source || "";
  if (title || provider) keys.push(`title:${provider}:${title}`);
  return keys;
}

function renderInlineJson(payload) {
  if (jsonInline) jsonInline.textContent = JSON.stringify(payload || {}, null, 2);
}

function renderArtifacts(execution) {
  const providerResults = execution?.provider_results || [];
  const artifacts = providerResults.flatMap((result) =>
    Object.entries(result.debug_artifacts || {}).map(([name, path]) => ({ provider: result.provider, name, path }))
  );
  if (!artifacts.length) {
    setMuted(artifactsPanel, "No screenshots yet.");
    return;
  }
  artifactsPanel.classList.remove("muted");
  artifactsPanel.replaceChildren(...artifacts.map((artifact) => {
    const item = document.createElement("article");
    item.className = "artifact";
    const header = document.createElement("div");
    header.className = "artifact-header";
    header.append(titleBlock(`${providerLabel(artifact.provider)} ${artifact.name}`, artifact.path));
    header.append(linkLine("Open", artifactUrl(artifact.path), "Open"));
    item.append(header);
    if (/\.(png|jpg|jpeg|webp)$/i.test(artifact.path)) {
      const image = document.createElement("img");
      image.src = artifactUrl(artifact.path);
      image.alt = `${artifact.provider} ${artifact.name}`;
      item.append(image);
    }
    return item;
  }));
}

function titleBlock(title, subtitle) {
  const block = document.createElement("div");
  const strong = document.createElement("strong");
  strong.textContent = title;
  block.append(strong);
  if (subtitle) {
    const small = document.createElement("div");
    small.className = "muted";
    small.textContent = subtitle;
    block.append(small);
  }
  return block;
}

function keyValue(key, value) {
  const item = document.createElement("div");
  item.className = "kv";
  const label = document.createElement("strong");
  label.textContent = key;
  const text = document.createElement("span");
  text.textContent = String(value);
  item.append(label, text);
  return item;
}

function statusRow(label, value, kind) {
  const row = document.createElement("div");
  row.className = "status-row";
  row.append(titleBlock(label, value), badge(value, kind));
  return row;
}

function badge(text, kind) {
  const item = document.createElement("span");
  item.className = `badge ${kind || ""}`.trim();
  item.textContent = text;
  return item;
}

function paragraph(text) {
  const p = document.createElement("p");
  p.textContent = text;
  p.style.marginTop = "10px";
  return p;
}

function listBlock(label, items) {
  const wrapper = document.createElement("div");
  wrapper.className = "facts";
  const title = document.createElement("span");
  title.textContent = label;
  wrapper.append(title, ...items.map((item) => {
    const span = document.createElement("span");
    span.textContent = item;
    return span;
  }));
  return wrapper;
}

function filterBox(label, values) {
  const box = document.createElement("div");
  box.className = "filter-box";
  const strong = document.createElement("strong");
  strong.textContent = label;
  const text = document.createElement("span");
  text.textContent = values.length ? values.join(", ") : "none";
  box.append(strong, text);
  return box;
}

function factRow(values) {
  const row = document.createElement("div");
  row.className = "facts";
  row.append(...values.map((value) => {
    const span = document.createElement("span");
    span.textContent = value;
    return span;
  }));
  return row;
}

function imageStrip(urls) {
  const strip = document.createElement("div");
  strip.className = "listing-media";
  urls.forEach((url) => {
    const image = document.createElement("img");
    image.src = url;
    image.alt = "Listing image";
    image.loading = "lazy";
    strip.append(image);
  });
  return strip;
}

function linkLine(label, href, text) {
  const line = document.createElement("p");
  line.style.marginTop = "10px";
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.target = "_blank";
  anchor.rel = "noreferrer";
  anchor.textContent = text || href;
  line.append(`${label}: `, anchor);
  return line;
}

function setMuted(element, text) {
  element.classList.add("muted");
  element.textContent = text;
}

function artifactUrl(path) {
  return `/artifact?path=${encodeURIComponent(path)}`;
}

function summaryText(intent, execution) {
  const records = execution?.records || [];
  if (records.length === 1) return "I found 1 listing for this search.";
  if (records.length) return `I found ${records.length} listings for this search.`;
  const location = intent.location || "your target area";
  const budget = priceRange(intent);
  const place = join(intent.type_of_places) || join(intent.property_types) || "housing";
  return `Searching for ${place} in ${location}${budget ? `, ${budget}` : ""}.`;
}

function bucketLabel(bucket) {
  const labels = {
    recommended: "Recommended",
    needs_verification: "Needs verification",
    excluded: "Excluded",
  };
  return labels[bucket] || bucket;
}

function bucketKind(bucket) {
  if (bucket === "recommended") return "good";
  if (bucket === "excluded") return "bad";
  return "warn";
}

function keys(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (typeof value === "object") return Object.keys(value);
  return [String(value)];
}

function join(value) {
  if (!value) return "";
  if (Array.isArray(value)) return value.filter(Boolean).join(", ");
  return String(value);
}

function hasValue(value) {
  return value !== null && value !== undefined && String(value).trim() !== "";
}

function range(min, max) {
  if (min && max) return `${min}-${max}`;
  return min || max || "";
}

function dateRange(start, end) {
  if (start && end) return `${start} to ${end}`;
  return start || end || "";
}

function priceRange(intent) {
  if (intent.min_price && intent.max_price) return `$${intent.min_price}-$${intent.max_price}`;
  if (intent.max_price) return `up to $${intent.max_price}`;
  if (intent.min_price) return `from $${intent.min_price}`;
  return "";
}

function coordinateText(record) {
  if (record.listing_latitude != null && record.listing_longitude != null) {
    return `${record.listing_latitude}, ${record.listing_longitude}`;
  }
  return record.coordinates_status ? `coordinates: ${record.coordinates_status}` : "";
}

function imageValues(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === "string") return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
  return [];
}

function providerLabel(provider) {
  const labels = {
    ohana: "Ohana",
    rentalsource: "RentalSource",
    affordablehousing: "AffordableHousing",
  };
  return labels[provider] || provider || "Provider";
}

function labelForState(value) {
  const labels = {
    collecting: "Collecting",
    needs_clarification: "Needs clarification",
    planned: "Planned",
    execution_confirmation_requested: "Ready to run",
    executed: "Executed",
    blocked: "Blocked",
    error: "Error",
    reset: "Reset",
  };
  return labels[value] || value || "Ready";
}

handleResponse({ turn: { state: "collecting", message: "Tell me what you are looking for." }, payload: { state: "collecting" } });
