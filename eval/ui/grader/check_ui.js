// Hidden UI grader: runs the workspace's index.html scripts against a tiny fake DOM
// (no browser, no packages) and checks the rendered behavior.
// Supported page API: getElementById, createElement, appendChild/append/replaceChildren/removeChild,
// textContent, innerHTML (<li> only), hidden, style.display, value, setAttribute/removeAttribute
// ("hidden"), addEventListener, querySelector("#id"), querySelectorAll("tag").
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const assert = require("assert");

const root = process.argv[2];
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");

const decode = (s) => s.replace(/<[^>]*>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&amp;/g, "&");

class El {
  constructor(tag, attrs = {}) {
    this.tagName = tag.toUpperCase();
    this.attrs = attrs;
    this.id = attrs.id || "";
    this.children = [];
    this.own = "";
    this.hidden = "hidden" in attrs;
    this.value = attrs.value || "";
    this.style = { display: "" };
    this.listeners = {};
  }
  get textContent() { return this.own + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.children = []; this.own = String(v); }
  set innerHTML(v) {
    this.children = []; this.own = "";
    for (const m of String(v).matchAll(/<li([^>]*)>([\s\S]*?)<\/li>/gi)) {
      const li = new El("li", /\bhidden\b/.test(m[1]) ? { hidden: "" } : {});
      li.own = decode(m[2]);
      this.children.push(li);
    }
    if (!this.children.length) this.own = decode(String(v));
  }
  get innerHTML() { return this.textContent; }
  appendChild(c) { this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.children.push(typeof c === "string" ? Object.assign(new El("span"), { own: c }) : c)); }
  replaceChildren(...cs) { this.children = []; this.own = ""; this.append(...cs); }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
  setAttribute(k, v) { this.attrs[k] = v; if (k === "hidden") this.hidden = true; if (k === "value") this.value = v; }
  removeAttribute(k) { delete this.attrs[k]; if (k === "hidden") this.hidden = false; }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); }
  dispatch(t) { (this.listeners[t] || []).forEach((fn) => fn({ type: t, target: this, currentTarget: this })); }
  all(tag) { return this.children.flatMap((c) => [c, ...c.all(tag)]).filter((c) => !tag || c.tagName === tag.toUpperCase()); }
  get isHidden() { return this.hidden || this.style.display === "none"; }
}

const byId = {};
for (const m of html.matchAll(/<(\w+)([^>]*\bid="[^"]+"[^>]*)>/g)) {
  const attrs = {};
  for (const a of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] === undefined ? "" : a[2];
  const el = new El(m[1], attrs);
  const end = html.indexOf("</" + m[1] + ">", m.index);
  if (end > 0 && m[1] !== "input") {
    const inner = html.slice(m.index + m[0].length, end);
    if (!/</.test(inner)) el.own = decode(inner).trim();
  }
  byId[attrs.id] = el;
}

const docListeners = {};
const document = {
  getElementById: (id) => byId[id] || null,
  querySelector: (s) => (s[0] === "#" ? byId[s.slice(1)] || null : null),
  querySelectorAll: (s) => Object.values(byId).flatMap((e) => e.all(s)),
  createElement: (t) => new El(t),
  addEventListener: (t, fn) => (docListeners[t] = docListeners[t] || []).push(fn),
};
const sandbox = { document, console };
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const m of html.matchAll(/<script([^>]*)>([\s\S]*?)<\/script>/g)) {
  const src = /src="([^"]+)"/.exec(m[1]);
  const code = src ? fs.readFileSync(path.join(root, src[1]), "utf8") : m[2];
  vm.runInContext(code, sandbox, { filename: src ? src[1] : "inline" });
}
(docListeners.DOMContentLoaded || []).forEach((fn) => fn({ type: "DOMContentLoaded" }));

const need = (id) => { assert.ok(byId[id], `missing #${id}`); return byId[id]; };
const list = need("list"), q = need("q"), count = need("count"), empty = need("empty");
const shown = () => list.all("li").filter((li) => !li.isHidden).map((li) => li.textContent);
const type = (v) => { q.value = v; q.dispatch("input"); };
const ITEMS = ["Apple", "Banana", "Apricot", "Cherry", "Tom & <Jerry>", "grape"];

assert.deepStrictEqual(shown(), ITEMS, "initial list");
assert.strictEqual(count.textContent.trim(), "6 of 6 shown", "initial count");
assert.ok(empty.isHidden, "#empty hidden on first load");
assert.match(empty.textContent, /No matches/, "#empty text");

type("AP");
assert.deepStrictEqual(shown(), ["Apple", "Apricot", "grape"], "case-insensitive match");
assert.strictEqual(count.textContent.trim(), "3 of 6 shown");
assert.ok(empty.isHidden);

type("  apple ");
assert.deepStrictEqual(shown(), ["Apple"], "query is trimmed");
assert.strictEqual(count.textContent.trim(), "1 of 6 shown");

type("<jerry");
assert.deepStrictEqual(shown(), ["Tom & <Jerry>"], "text stays literal");

type("zzz");
assert.deepStrictEqual(shown(), []);
assert.strictEqual(count.textContent.trim(), "0 of 6 shown");
assert.ok(!empty.isHidden, "#empty visible with no matches");

type("");
assert.deepStrictEqual(shown(), ITEMS, "empty query shows all");
assert.strictEqual(count.textContent.trim(), "6 of 6 shown");
assert.ok(empty.isHidden, "#empty hidden again");
console.log("ui grader: all checks passed");
