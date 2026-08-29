
let MENU_DATA = null;
let currentCategoryIndex = 0;

const currencyFormatter = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0
});

const TAG_STYLES = {
  "Chefs Recommendation": "border-brass/40 bg-brass/10 text-[#8A6A38]",
  "Non Vegetarian": "border-terra/30 bg-terra/[0.07] text-terra",
  "Contains Eggs": "border-[#C9971F]/40 bg-[#C9971F]/10 text-[#8F6A12]"
};
const TAG_DEFAULT_STYLE = "border-navy/20 bg-navy/[0.06] text-navy/70";


const FALLBACK_ITEM_IMAGE = "https://images.unsplash.com/photo-1621996346565-e3dbc646d9a9?q=80&w=400&auto=format&fit=crop";

function getItemImageUrl(item) { return item.image_url || FALLBACK_ITEM_IMAGE; }

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatPrice(amount) {
  return currencyFormatter.format(amount).replace("₹", "₹ ");
}

function buildPricingHtml(pricing) {
  const tiers = Object.entries(pricing || {});
  if (!tiers.length) return "";
  const blocks = tiers
    .map(function (pair) {
      var tier = pair[0];
      var amount = pair[1];
      return (
        '<div class="text-right">' +
        '<p class="whitespace-nowrap text-[15px] font-semibold tabular-nums text-gray-900">' +
        formatPrice(amount) +
        "</p>" +
        (tiers.length > 1 ? '<p class="mt-0.5 text-[9px] tracking-widest font-bold uppercase text-gray-400">' + escapeHtml(tier === "Non Veg" ? "Non-Veg" : tier) + "</p>" : "") +
        "</div>"
      );
    })
    .join("");
  return (
    '<div class="flex shrink-0 flex-col items-end justify-center gap-1.5">' +
    blocks +
    "</div>"
  );
}
function buildTagsHtml(tags) {
  if (!tags || !tags.length) return "";
  var chips = tags.map(function (tag) {
    var style = TAG_STYLES[tag] || TAG_DEFAULT_STYLE;
    return (
      '<span class="inline-flex items-center rounded-full border px-2.5 py-1 text-[9px] font-semibold uppercase tracking-[0.18em] ' +
      style +
      '">' +
      escapeHtml(tag) +
      "</span>"
    );
  });
  return '<div class="mt-2.5 flex flex-wrap gap-1.5">' + chips.join("") + "</div>";
}

function buildItemCard(item, index) {
  var safeName = escapeHtml(item.item_name);
  var tiers = Object.entries(item.pricing || {});
  var isSingleVariant = tiers.length === 1;
  
  var btnAttrs = 'data-item="' + escapeHtml(item.item_name) + '"';
  if (isSingleVariant) {
     btnAttrs += ' data-tier="' + escapeHtml(tiers[0][0]) + '" data-price="' + tiers[0][1] + '" data-single="true"';
  } else {
     btnAttrs += ' data-single="false"';
  }

  return (
    /* "menu-card" is kept alongside "menu-item" so the existing click,
       keyboard and search-filter bindings continue to work unchanged. */
    '<article class="menu-card menu-item rise" ' +
    'tabindex="0" role="button" aria-label="View details for ' +
    safeName +
    '" data-index="' +
    index +
    '" style="animation-delay:' +
    Math.min(index * 55, 440) +
    'ms">' +
    '<img class="menu-item-img" src="' +
    escapeHtml(getItemImageUrl(item)) +
    '" alt="' +
    safeName +
    '" loading="lazy" decoding="async" onerror="this.onerror=null; this.src=\'' +
    FALLBACK_ITEM_IMAGE +
    '\';" />' +
    '<div class="menu-item-info">' +
    '<h3 class="break-words">' +
    safeName +
    "</h3>" +
    '<p class="break-words">' +
    escapeHtml(item.description) +
    "</p>" +
    buildTagsHtml(item.tags) +
    "</div>" +
    '<div class="menu-item-action">' +
    buildPricingHtml(item.pricing) +
    '<button type="button" class="add-to-cart-btn" aria-label="Add to cart" onclick="event.stopPropagation(); handleAddToCartClick(this)" ' + btnAttrs + '>' +
    '+' +
    '</button>' +
    '</div>' +
    "</article>"
  );
}

function buildCategorySection(category) {
  var noteHtml = category.note
    ? '<p class="mt-1.5 font-display text-sm italic text-stone-500">' +
      escapeHtml(category.note) +
      "</p>"
    : "";
  var itemsHtml = category.items.map(buildItemCard).join("");
  return (
    '<section class="pt-2">' +
    '<div class="flex items-center gap-4">' +
    '<h2 class="font-display text-[26px] font-semibold uppercase tracking-[0.12em] text-navy">' +
    escapeHtml(category.category_name) +
    "</h2>" +
    '<span class="ornament-line flex-1" aria-hidden="true"></span>' +
    "</div>" +
    noteHtml +
    '<div class="mt-6 space-y-4">' +
    itemsHtml +
    "</div></section>"
  );
}

function buildLegend(legend) {
  if (!legend || !legend.length) return "";
  var rows = legend
    .map(function (entry) {
      return (
        '<li class="flex items-center gap-3">' +
        '<span class="block h-1.5 w-1.5 rotate-45 bg-brass" aria-hidden="true"></span>' +
        escapeHtml(entry) +
        "</li>"
      );
    })
    .join("");
  return (
    '<div class="rounded-2xl border border-navy/10 bg-white/70 p-5">' +
    '<h4 class="text-[10px] font-semibold uppercase tracking-[0.32em] text-stone-400">Legend</h4>' +
    '<ul class="mt-3.5 space-y-2.5 text-xs font-medium text-stone-600">' +
    rows +
    "</ul></div>"
  );
}

var itemModal = document.getElementById("item-modal");
var modalBackBtn = document.getElementById("modal-back");
var modalImage = document.getElementById("modal-image");
var modalName = document.getElementById("modal-name");
var modalTags = document.getElementById("modal-tags");
var modalPricing = document.getElementById("modal-pricing");
var modalInfoGrid = document.getElementById("modal-info-grid");
var lastFocusedCard = null;

function buildHeroTags(item) {
  var tiers = Object.keys(item.pricing || {});
  var chips = [];
  if (tiers.indexOf("Veg") > -1) {
    chips.push(["Veg", "olive"]);
  } else if (tiers.indexOf("Non Veg") > -1) {
    chips.push(["Non Veg", "terra"]);
  }
  (item.tags || []).forEach(function (tag) {
    if (tag === "Non Vegetarian") chips.push([tag, "terra"]);
    else if (tag === "Chefs Recommendation" || tag === "Contains Eggs") chips.push([tag, "gold"]);
    else chips.push([tag, "neutral"]);
  });
  if (!chips.length) return "";
  return chips
    .map(function (chip) {
      return '<span class="tag-chip tag-chip--' + chip[1] + '">' + escapeHtml(chip[0]) + "</span>";
    })
    .join("");
}

var DISH_META = {
  "Penne Alfredo": { spice: "Mild", time: "~18 min", portion: "Serves 1 · 250 g", allergens: "Dairy, Gluten" },
  "Arrabiatta Red Pasta": { spice: "Spicy", time: "~15 min", portion: "Serves 1 · 260 g", allergens: "Gluten" },
  "Pasta in Parma Rosa Sauce": { spice: "Mild", time: "~17 min", portion: "Serves 1 · 270 g", allergens: "Dairy, Gluten" },
  "Spaghetti Marinara": { spice: "Mild", time: "~16 min", portion: "Serves 1 · 240 g", allergens: "Gluten" },
  "Spaghetti Aglio-e-Olio peperoncino": { spice: "Medium", time: "~12 min", portion: "Serves 1 · 230 g", allergens: "Gluten, Dairy" },
  "Spaghetti Meaty Alfredo": { spice: "Mild", time: "~20 min", portion: "Serves 1 · 320 g", allergens: "Dairy, Gluten" },
  "Spaghetti Bolognaise": { spice: "Mild", time: "~22 min", portion: "Serves 1 · 300 g", allergens: "Gluten, Dairy" },
  "Butter Chicken Spaghetti": { spice: "Medium", time: "~20 min", portion: "Serves 1 · 300 g", allergens: "Dairy, Gluten, Nuts (trace)" },
  "Chilly Garlic Prawns Spaghetti": { spice: "Fiery", time: "~18 min", portion: "Serves 1 · 280 g", allergens: "Shellfish, Soy, Gluten" },
  "Lasagne Bolognaise": { spice: "Mild", time: "~25 min", portion: "Serves 1 · 340 g", allergens: "Gluten, Dairy, Egg" }
};
var DEFAULT_DISH_META = { spice: "Medium", time: "~15–20 min", portion: "Serves 1", allergens: "Ask the butler" };

function spiceAccent(value) {
  var v = String(value).toLowerCase();
  if (v === "fiery" || v === "spicy" || v === "hot") return "terra";
  if (v === "medium") return "gold";
  return "olive";
}

var INFO_ICONS = {
  spice: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-[17px] w-[17px]"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>',
  time: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-[17px] w-[17px]"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
  portion: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-[17px] w-[17px]"><path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/></svg>',
  allergens: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-[17px] w-[17px]"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>'
};

function buildInfoCard(label, value, iconKey, accent) {
  return (
    '<article class="info-card" data-accent="' + accent + '">' +
    '<span class="info-card-icon" aria-hidden="true">' + INFO_ICONS[iconKey] + "</span>" +
    '<p class="info-card-label">' + label + "</p>" +
    '<p class="info-card-value">' + escapeHtml(value) + "</p>" +
    "</article>"
  );
}

function fillModal(item) {
  var imageUrl = getItemImageUrl(item.item_name);
  modalImage.onerror = function () {
    modalImage.onerror = null;
    modalImage.src = FALLBACK_ITEM_IMAGE;
  };
  modalImage.src = imageUrl;
  modalImage.alt = item.item_name;

  modalName.textContent = item.item_name;
  modalTags.innerHTML = buildHeroTags(item);

  var meta = DISH_META[item.item_name] || DEFAULT_DISH_META;
  modalInfoGrid.innerHTML =
    buildInfoCard("Spice Level", meta.spice, "spice", spiceAccent(meta.spice)) +
    buildInfoCard("Prep Time", meta.time, "time", "olive") +
    buildInfoCard("Portion Size", meta.portion, "portion", "olive") +
    buildInfoCard("Allergens", meta.allergens, "allergens", "gold");

  var tiers = Object.entries(item.pricing || {});
  modalPricing.innerHTML = tiers
    .map(function (pair) {
      var tier = pair[0];
      var amount = pair[1];
      return (
        '<div class="text-center">' +
        '<p class="dish-price whitespace-nowrap">' +
        formatPrice(amount) +
        "</p>" +
        '<p class="dish-price-tier">' +
        escapeHtml(tier === "Non Veg" ? "Non-Veg" : tier) +
        "</p>" +
        "</div>"
      );
    })
    .join("");
}

function openItemModal(triggerEl, item) {
  lastFocusedCard = triggerEl || null;
  currentItemName = item.item_name;
  fillModal(item);
  resetChat(item.item_name);
  
  // Fix the auto-scroll: target the actual scrollable container instead of the outer modal
  var scroller = itemModal.querySelector(".overflow-y-auto");
  if (scroller) {
    scroller.scrollTop = 0;
  }
  
  document.body.style.overflow = "hidden";
  itemModal.setAttribute("aria-hidden", "false");
  requestAnimationFrame(function () {
    itemModal.classList.remove("translate-y-full");
    itemModal.classList.add("translate-y-0");
  });
  window.setTimeout(function () {
    modalBackBtn.focus();
  }, 320);
}

function closeItemModal() {
  chatInput.blur();
  itemModal.classList.add("translate-y-full");
  itemModal.classList.remove("translate-y-0");
  itemModal.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  window.setTimeout(function () {
    if (!itemModal.classList.contains("translate-y-0") &&
        typeof modalImage !== "undefined") {
      modalImage.removeAttribute("src");
    }
  }, 320);
  if (lastFocusedCard && typeof lastFocusedCard.focus === "function") {
    lastFocusedCard.focus();
    lastFocusedCard = null;
  }
}

function renderMenu(data) {
  var root = document.getElementById("menu-root");
  root.innerHTML =
    '<div class="mb-2 flex items-center justify-between">' +
    '<p class="text-[10px] font-semibold uppercase tracking-[0.4em] text-stone-400">' +
    escapeHtml(data.menu_section) +
    "</p></div>" +
    data.categories.map(buildCategorySection).join("");

  Array.prototype.forEach.call(root.querySelectorAll(".menu-card"), function (card) {
    card.addEventListener("click", function () {
      var item = data.categories[currentCategoryIndex].items[parseInt(card.getAttribute("data-index"), 10)];
      openItemModal(card, item);
    });
    card.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        var item = data.categories[currentCategoryIndex].items[parseInt(card.getAttribute("data-index"), 10)];
        openItemModal(card, item);
      }
    });
  });

  document.getElementById("legend-root").innerHTML = buildLegend(data.legend);
}

modalBackBtn.addEventListener("click", closeItemModal);

document.addEventListener("keydown", function (event) {
  if (
    event.key === "Escape" &&
    !itemModal.classList.contains("translate-y-full")
  ) {
    closeItemModal();
  }
});

/* ---------- AI Butler Chat (embedded in the dish modal) ---------- */

var currentItemName = null;

var chatHistory = document.getElementById("chat-history");
var chatForm = document.getElementById("chat-form");
var chatInput = document.getElementById("chat-input");
var chatSendBtn = document.getElementById("chat-send");
var promptRail = document.getElementById("prompt-rail");
var chatContextName = document.getElementById("chat-context-name");

var chatLog = [];
var lastChatDish = null;

function escapeChat(value) {
  return escapeHtml(value).replace(/\n/g, "<br>");
}

function appendUserBubble(text) {
  chatLog.push({ role: "user", content: text });
  var bubble = document.createElement("div");
  bubble.className = "bubble-row bubble-row--user";
  bubble.innerHTML =
    '<div class="bubble bubble--user">' +
    escapeChat(text) +
    "</div>";
  chatHistory.appendChild(bubble);
  scrollToLatest();
}

function appendAiBubble(text) {
  chatLog.push({ role: "assistant", content: text });
  var bubble = document.createElement("div");
  bubble.className = "bubble-row bubble-row--ai";
  bubble.innerHTML =
    '<div class="bubble bubble--ai">' +
    escapeChat(text) +
    "</div>";
  chatHistory.appendChild(bubble);
  scrollToLatest();
}

function scrollToLatest() {
  var scroller = chatHistory.closest(".overflow-y-auto");
  if (scroller) scroller.scrollTop = scroller.scrollHeight;
}

function appendThinkingIndicator() {
  var wrap = document.createElement("div");
  wrap.id = "chat-thinking";
  wrap.className = "bubble-row bubble-row--ai";
  wrap.innerHTML =
    '<div class="bubble bubble--ai italic">' +
    '<span class="thinking-dots" aria-hidden="true">' +
    '<span class="thinking-dot"></span>' +
    '<span class="thinking-dot"></span>' +
    '<span class="thinking-dot"></span>' +
    "</span>" +
    "The butler is thinking&hellip;" +
    "</div>";
  chatHistory.appendChild(wrap);
  scrollToLatest();
}

function removeThinkingIndicator() {
  var el = document.getElementById("chat-thinking");
  if (el) el.remove();
}

function resetChat(dishName) {
  if (lastChatDish === dishName) return;
  lastChatDish = dishName;
  chatLog = [];
  chatHistory.innerHTML = "";
  appendAiBubble(
    "Good evening! You're admiring the " +
      dishName +
      " — an excellent choice. Ask me about the heat, the portion, or what to sip alongside it."
  );
}

function setButlerBusy(busy) {
  chatSendBtn.disabled = busy;
  promptRail.classList.toggle("is-disabled", busy);
}

async function handleChatSubmit(event, presetText) {
  if (event) event.preventDefault();
  var userInput = String(presetText || chatInput.value || "").trim();
  if (!userInput) return;
  if (!currentItemName) {
    appendAiBubble("Please pick a dish from the menu first.");
    return;
  }
  if (chatSendBtn.disabled) return;

  var outgoingHistory = chatLog.slice(-8);
  appendUserBubble(userInput);
  if (!presetText) chatInput.value = "";
  appendThinkingIndicator();
  setButlerBusy(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        item_name: currentItemName,
        user_message: userInput,
        history: outgoingHistory
      })
    });
    const data = await response.json();
    removeThinkingIndicator();
    if (response.ok) {
      appendAiBubble(data.reply);
    } else {
      appendAiBubble(data.detail || "Sorry, something went wrong. Please try again.");
    }
  } catch (error) {
    removeThinkingIndicator();
    appendAiBubble("I could not reach the kitchen (backend). Is the server running?");
  } finally {
    setButlerBusy(false);
  }
}

promptRail.addEventListener("click", function (event) {
  var pill = event.target.closest("[data-prompt]");
  if (!pill) return;
  handleChatSubmit(null, pill.getAttribute("data-prompt"));
});

chatForm.addEventListener("submit", handleChatSubmit);

/* ---------- Cart / Order Preview ---------- */

var TRASH_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="h-4 w-4" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="m19 6-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>';

var EMPTY_CART_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="mx-auto h-12 w-12" aria-hidden="true"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>';

var cartDrawer = document.getElementById("cart-drawer");
var cartScrim = document.getElementById("cart-scrim");
var cartBackBtn = document.getElementById("cart-back");
var cartItemsEl = document.getElementById("cart-items");
var cartSubtotalEl = document.getElementById("cart-subtotal");
var cartCountEl = document.getElementById("cart-count");
var cartState = [];

function findMenuItem(name) {
  for (var c = 0; c < MENU_DATA.categories.length; c++) {
    var items = MENU_DATA.categories[c].items;
    for (var i = 0; i < items.length; i++) {
      if (items[i].item_name === name) return items[i];
    }
  }
  return null;
}

function buildCartItemHtml(entry, index) {
  var safeName = escapeHtml(entry.item_name);
  return (
    '<li class="cart-item">' +
    '<img src="' + escapeHtml(getItemImageUrl(entry.item_name)) + '" alt="' + safeName +
    '" loading="lazy" decoding="async" onerror="this.onerror=null; this.src=\'' +
    FALLBACK_ITEM_IMAGE + '\';" />' +
    '<div class="cart-item-info">' +
    "<h3>" + safeName + "</h3>" +
    "<p>" + escapeHtml(entry.description) + "</p>" +
    "</div>" +
    '<div class="cart-item-side">' +
    '<div class="qty-selector" role="group" aria-label="Quantity for ' + safeName + '">' +
    '<button type="button" class="qty-btn" data-action="dec" data-index="' + index + '" aria-label="Decrease quantity"' +
    (entry.qty <= 1 ? " disabled" : "") + ">&minus;</button>" +
    '<span class="qty-value">' + entry.qty + "</span>" +
    '<button type="button" class="qty-btn" data-action="inc" data-index="' + index + '" aria-label="Increase quantity">+</button>' +
    "</div>" +
    '<p class="cart-item-price">' + formatPrice(entry.price * entry.qty) + "</p>" +
    '<button type="button" class="trash-btn" data-action="remove" data-index="' + index + '" aria-label="Remove ' +
    safeName + ' from order">' + TRASH_ICON + "</button>" +
    "</div></li>"
  );
}

function updateCartBadge() {
  var count = cartState.reduce(function (sum, entry) { return sum + entry.qty; }, 0);
  cartCountEl.textContent = count;
  cartCountEl.classList.toggle("hidden", count === 0);
}

function updateCartSubtotal() {
  var total = cartState.reduce(function (sum, entry) {
    return sum + entry.price * entry.qty;
  }, 0);
  cartSubtotalEl.textContent = formatPrice(total);
  var placeBtn = document.getElementById("place-order-btn");
  if (placeBtn) {
    placeBtn.textContent = "Place Order · " + formatPrice(total);
    placeBtn.disabled = cartState.length === 0;
  }
}

function renderCart() {
  if (cartState.length) {
    cartItemsEl.innerHTML = cartState.map(buildCartItemHtml).join("");
  } else {
    cartItemsEl.innerHTML =
      '<li class="cart-empty">' + EMPTY_CART_ICON +
      "<h3>Your order is empty</h3>" +
      "<p>Add dishes from the menu to get started.</p></li>";
  }
  updateCartBadge();
  updateCartSubtotal();
}

function openCart() {
  renderCart();
  document.body.classList.add("cart-open");
  cartDrawer.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  window.setTimeout(function () {
    cartBackBtn.focus();
  }, 340);
}

function closeCart() {
  document.body.classList.remove("cart-open");
  cartDrawer.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

cartItemsEl.addEventListener("click", function (event) {
  var control = event.target.closest("[data-action]");
  if (!control) return;
  var index = parseInt(control.getAttribute("data-index"), 10);
  var entry = cartState[index];
  if (!entry) return;
  switch (control.getAttribute("data-action")) {
    case "inc":
      entry.qty += 1;
      break;
    case "dec":
      if (entry.qty <= 1) return;
      entry.qty -= 1;
      break;
    case "remove":
      cartState.splice(index, 1);
      break;
    default:
      return;
  }
  renderCart();
});

document.getElementById("cart-open").addEventListener("click", openCart);
cartBackBtn.addEventListener("click", closeCart);
cartScrim.addEventListener("click", closeCart);

document.addEventListener("keydown", function (event) {
  if (
    event.key === "Escape" &&
    cartDrawer.getAttribute("aria-hidden") === "false"
  ) {
    closeCart();
  }
});

renderCart();

// QR codes can point to /menu?table=12. Prefill the table automatically.
var tableFromQr = new URLSearchParams(window.location.search).get("table");
if (tableFromQr) document.getElementById("order-table").value = tableFromQr;

renderMenu(MENU_DATA);


async function placeOrder() {
  var btn = document.getElementById("place-order-btn");
  var statusEl = document.getElementById("order-status");
  var table = document.getElementById("order-table").value.trim();
  var notes = document.getElementById("order-notes").value.trim();
  if (!cartState.length) { showToast("Add at least one dish first."); return; }
  if (!table) { showToast("Please enter your table number."); document.getElementById("order-table").focus(); return; }
  var tableMatch = table.match(/\d+/);
  var tableNum = tableMatch ? parseInt(tableMatch[0], 10) : null;
  if (tableNum === null || tableNum < 1 || tableNum > 12) {
    showToast("Invalid table number. Table '" + table + "' does not exist (1-12).");
    document.getElementById("order-table").focus();
    return;
  }
  btn.disabled = true;
  btn.textContent = "Sending order…";
  statusEl.textContent = "Sending your order to the cafe…";
  try {
    var response = await fetch("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        table_number: table,
        notes: notes,
        items: cartState.map(function (entry) {
          return { item_name: entry.item_name, tier: entry.tier, quantity: entry.qty };
        })
      })
    });
    var data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Could not place order.");
    cartState = [];
    renderCart();
    statusEl.innerHTML = "Order <strong>" + escapeHtml(data.order_number) + "</strong> received by the cafe. You can close this panel.";
    showToast("Order placed successfully!");
  } catch (error) {
    statusEl.textContent = error.message;
    showToast(error.message);
    renderCart();
  }
}

// --- Added Logic ---


// --- Variant Selector & Add To Cart Logic ---

var currentVariantItem = null;

function handleAddToCartClick(btn) {
  var isSingle = btn.getAttribute("data-single") === "true";
  if (isSingle) {
    addToCart(btn);
    showToast("Added to cart!");
  } else {
    var itemName = btn.getAttribute("data-item");
    openVariantSelector(itemName);
  }
}

function openVariantSelector(itemName) {
  var item = findMenuItem(itemName);
  if (!item) return;
  currentVariantItem = item;
  
  document.getElementById("variant-title").textContent = item.item_name;
  
  var optionsHtml = "";
  var tiers = Object.entries(item.pricing || {});
  tiers.forEach(function(pair, idx) {
    var tier = pair[0];
    var price = pair[1];
    var isChecked = idx === 0 ? "checked" : "";
    optionsHtml += `
      <label class="flex items-center justify-between p-3 mb-3 border border-gray-200 rounded-xl cursor-pointer hover:bg-gray-50 transition-colors variant-label">
        <div class="flex items-center gap-3">
          <input type="radio" name="dish-variant" value="${escapeHtml(tier)}" data-price="${price}" class="w-5 h-5 text-navy focus:ring-navy border-gray-300" ${isChecked}>
          <span class="font-medium text-navy text-[15px]">${escapeHtml(tier === 'Non Veg' ? 'Non-Veg' : tier)}</span>
        </div>
        <span class="font-semibold text-gray-900">${formatPrice(price)}</span>
      </label>
    `;
  });
  
  document.getElementById("variant-options").innerHTML = optionsHtml;
  
  var scrim = document.getElementById("variant-scrim");
  var sheet = document.getElementById("variant-sheet");
  
  scrim.classList.remove("opacity-0", "pointer-events-none");
  scrim.classList.add("opacity-100");
  
  sheet.classList.remove("translate-y-full");
  sheet.classList.add("translate-y-0");
}

function closeVariantSelector() {
  var scrim = document.getElementById("variant-scrim");
  var sheet = document.getElementById("variant-sheet");
  
  sheet.classList.remove("translate-y-0");
  sheet.classList.add("translate-y-full");
  
  scrim.classList.remove("opacity-100");
  scrim.classList.add("opacity-0", "pointer-events-none");
  
  currentVariantItem = null;
}

function confirmVariantSelection() {
  if (!currentVariantItem) return;
  
  var selectedRadio = document.querySelector('input[name="dish-variant"]:checked');
  if (!selectedRadio) return;
  
  var tier = selectedRadio.value;
  var price = parseFloat(selectedRadio.getAttribute("data-price"));
  
  addRawToCart(currentVariantItem.item_name, tier, price);
  
  closeVariantSelector();
  showToast("Added to cart!");
}

function addRawToCart(itemName, tier, price) {
  var menuItem = findMenuItem(itemName);
  if (!menuItem) return;
  
  var existing = null;
  for (var i = 0; i < cartState.length; i++) {
    if (cartState[i].item_name === itemName && cartState[i].tier === tier) {
      existing = cartState[i];
      break;
    }
  }
  
  if (existing) {
    existing.qty += 1;
  } else {
    cartState.push({
      item_name: menuItem.item_name,
      description: menuItem.description,
      tier: tier,
      price: price,
      qty: 1
    });
  }
  
  renderCart();
}

function addToCart(btn) {
  var itemName = btn.getAttribute("data-item");
  var tier = btn.getAttribute("data-tier");
  var price = parseFloat(btn.getAttribute("data-price"));
  
  addRawToCart(itemName, tier, price);
  
  if (btn.getAttribute("data-checking") === "true") return;
  var originalHtml = btn.innerHTML;
  var origClasses = btn.className;
  
  btn.setAttribute("data-checking", "true");
  btn.className = origClasses.replace("bg-sage-tint", "bg-sage").replace("text-sage-dark", "text-white");
  btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor" class="w-5 h-5 text-white"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>';
  
  setTimeout(function() {
    btn.innerHTML = originalHtml;
    btn.className = origClasses;
    btn.removeAttribute("data-checking");
  }, 1000);
}

function showToast(msg) {
  var toast = document.getElementById("toast-container");
  var msgEl = document.getElementById("toast-message");
  msgEl.textContent = msg;
  
  toast.classList.remove("opacity-0", "pointer-events-none", "translate-y-[-20px]");
  toast.classList.add("opacity-100", "translate-y-0");
  
  setTimeout(function() {
    toast.classList.remove("opacity-100", "translate-y-0");
    toast.classList.add("opacity-0", "pointer-events-none", "translate-y-[-20px]");
  }, 2500);
}

// Replace the old addToCart with the new logic


// Chef's special click
var heroBanner = document.querySelector(".hero-banner");
if (heroBanner) {
  heroBanner.style.cursor = "pointer";
  heroBanner.addEventListener("click", function() {
    var butterChicken = findMenuItem("Butter Chicken Spaghetti");
    if (butterChicken) {
      openItemModal(this, butterChicken);
    }
  });
}

// Search Bar Logic
var searchInput = document.querySelector(".search-bar input");
if (searchInput) {
  searchInput.addEventListener("input", function(e) {
    var query = e.target.value.toLowerCase();
    var cards = document.querySelectorAll(".menu-card");
    cards.forEach(function(card) {
      var title = card.querySelector("h3").textContent.toLowerCase();
      var desc = card.querySelector("p").textContent.toLowerCase();
      if (title.indexOf(query) > -1 || desc.indexOf(query) > -1) {
        card.style.display = "";
      } else {
        card.style.display = "none";
      }
    });
  });
}


async function loadMenuData() {
  try {
    const res = await fetch('/api/menu');
    MENU_DATA = await res.json();
    renderDynamicCategoryRail();
    renderMenu(MENU_DATA);
  } catch(e) {
    console.error("Failed to load menu", e);
  }
}

function renderDynamicCategoryRail() {
  const rail = document.getElementById("category-rail");
  let html = '';
  MENU_DATA.categories.forEach((cat, idx) => {
    const active = idx === 0 ? 'is-active' : '';
    const aria = idx === 0 ? 'aria-current="true"' : '';
    html += `<button type="button" class="category-pill ${active}" ${aria} onclick="switchCategory(${idx}, this)">${escapeHtml(cat.category_name)}</button>`;
  });
  rail.innerHTML = html;
}

function switchCategory(idx, btn) {
  currentCategoryIndex = idx;
  document.querySelectorAll(".category-pill").forEach(p => {
    p.classList.remove("is-active");
    p.removeAttribute("aria-current");
  });
  btn.classList.add("is-active");
  btn.setAttribute("aria-current", "true");
  
  if (searchInput) {
    searchInput.value = "";
    searchInput.dispatchEvent(new Event('input'));
  }
  
  renderMenu(MENU_DATA);
}

// Override renderMenu to only render current category
function renderMenu(data) {
  var root = document.getElementById("menu-root");
  root.innerHTML =
    '<div class="mb-2 flex items-center justify-between">' +
    '<p class="text-[10px] font-semibold uppercase tracking-[0.4em] text-stone-400">' +
    escapeHtml(data.menu_section) +
    "</p></div>" +
    buildCategorySection(data.categories[currentCategoryIndex]);

  Array.prototype.forEach.call(root.querySelectorAll(".menu-card"), function (card) {
    card.addEventListener("click", function () {
      var item = data.categories[currentCategoryIndex].items[parseInt(card.getAttribute("data-index"), 10)];
      openItemModal(card, item);
    });
    card.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        var item = data.categories[currentCategoryIndex].items[parseInt(card.getAttribute("data-index"), 10)];
        openItemModal(card, item);
      }
    });
  });

  document.getElementById("legend-root").innerHTML = buildLegend(data.legend);
}

window.addEventListener('DOMContentLoaded', function() {
  var splash = document.getElementById('splash-screen');
  var logoWrapper = document.getElementById('splash-logo-wrapper');
  var appShell = document.querySelector('.app-shell');
  setTimeout(function() { if (logoWrapper) logoWrapper.classList.add('animate-splash'); }, 150);
  setTimeout(function() {
    if (splash) splash.classList.add('hide-splash');
    if (appShell) appShell.classList.add('show-app');
    setTimeout(function() { if (splash) splash.remove(); }, 1000);
  }, 1800);
  
  loadMenuData(); // Fetch Data on load!
});
