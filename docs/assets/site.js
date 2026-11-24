/* Shared code for the qpcp-proofs site. All data is read from public GitHub endpoints. */
(function () {
  "use strict";

  var CFG = {
    owner: "nareshgoud274",
    repo: "qpcp-proofs",
    // Set this to your GitHub Sponsors (or other) page once it exists, for example
    // "https://github.com/sponsors/nareshgoud274". Leave empty while payments are closed.
    sponsorUrl: "",
    // Plain statements of what support pays for. Shown on the Support page.
    sponsorUses: []
  };

  var repoUrl = "https://github.com/" + CFG.owner + "/" + CFG.repo;
  var raw = "https://raw.githubusercontent.com/" + CFG.owner + "/" + CFG.repo + "/main/";
  var api = "https://api.github.com/repos/" + CFG.owner + "/" + CFG.repo;

  var PAGES = [
    ["index.html", "Map"],
    ["live.html", "Live"],
    ["updates.html", "Updates"],
    ["how.html", "How it works"],
    ["contributors.html", "Contributors"],
    ["about.html", "What this is and is not"],
    ["sponsors.html", "Support"]
  ];

  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (k === "text") e.textContent = attrs[k];
        else if (k === "class") e.className = attrs[k];
        else e.setAttribute(k, attrs[k]);
      });
    }
    (kids || []).forEach(function (c) {
      e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return e;
  }

  function link(href, text, cls) {
    var a = el("a", { href: href, text: text });
    if (cls) a.className = cls;
    return a;
  }

  // Small per-tab cache so moving between pages does not spend GitHub's
  // anonymous request allowance. Storage can be unavailable; then we just fetch.
  function cacheGet(key, maxAgeMs) {
    try {
      var hit = JSON.parse(sessionStorage.getItem(key) || "null");
      if (hit && Date.now() - hit.t < maxAgeMs) return hit.v;
    } catch (e) { /* ignore */ }
    return null;
  }
  function cacheSet(key, value) {
    try { sessionStorage.setItem(key, JSON.stringify({ t: Date.now(), v: value })); } catch (e) { /* ignore */ }
  }

  function getJson(url, maxAgeMs) {
    var key = "qpcp:" + url;
    var hit = maxAgeMs ? cacheGet(key, maxAgeMs) : null;
    if (hit) return Promise.resolve(hit);
    return fetch(url, { headers: { Accept: "application/vnd.github+json" } }).then(function (r) {
      if (!r.ok) throw new Error(url + " returned " + r.status);
      return r.json();
    }).then(function (v) { cacheSet(key, v); return v; });
  }

  // GitHub returns at most 100 rows per request; follow the pages.
  function getPaged(url, maxAgeMs, maxPages) {
    var out = [];
    function page(n) {
      return getJson(url + "&per_page=100&page=" + n, maxAgeMs).then(function (rows) {
        out = out.concat(rows);
        return rows.length === 100 && n < maxPages ? page(n + 1) : out;
      });
    }
    return page(1);
  }

  function ago(iso) {
    if (!iso) return "";
    var s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 90) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago";
    if (s < 86400 * 30) return Math.round(s / 86400) + " d ago";
    return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function stepOf(title) {
    var m = /\b(S\d{3})\b/.exec(title || "");
    return m ? m[1] : null;
  }

  /* Loads the step list and its live status. maxAgeMs controls cache reuse. */
  function loadCore(maxAgeMs) {
    var age = maxAgeMs === undefined ? 120000 : maxAgeMs;
    return getJson(raw + "steps.json", 600000).then(function (steps) {
      return Promise.all([
        getPaged(api + "/issues?labels=step&state=all", age, 10),
        getPaged(api + "/pulls?state=closed&sort=updated&direction=desc", age, 10),
        getJson(api + "/pulls?state=open&per_page=50", age)
      ]).then(function (r) { return build(steps, r[0], r[1], r[2]); });
    });
  }

  function build(steps, issues, closedPulls, openPulls) {
    var issueBy = {};
    issues.forEach(function (i) {
      var id = stepOf(i.title);
      if (id && !i.pull_request) issueBy[id] = i;
    });

    var mergedBy = {};
    closedPulls.forEach(function (p) {
      var id = stepOf(p.title);
      if (id && p.merged_at && p.user && !mergedBy[id]) mergedBy[id] = p;
    });

    var checking = {};
    openPulls.forEach(function (p) {
      var id = stepOf(p.title);
      if (id) checking[id] = p;
    });

    var people = {};
    var out = steps.map(function (s) {
      var issue = issueBy[s.id], pr = mergedBy[s.id];
      var status = "open", who = "", when = "";
      if (issue && issue.state === "closed") {
        status = "proved";
        who = pr ? pr.user.login : "";
        when = pr ? pr.merged_at : issue.closed_at;
        if (who) {
          people[who] = people[who] || [];
          people[who].push(s.id);
        }
      } else if (issue && (issue.labels || []).some(function (l) { return l.name === "claimed"; })) {
        status = "claimed";
        who = (issue.assignees || []).map(function (a) { return a.login; }).join(", ");
        when = issue.updated_at;
      }
      return {
        id: s.id, title: s.title, section: s.section, difficulty: s.difficulty, deps: s.deps || [],
        status: status, who: who, when: when,
        url: issue ? issue.html_url : repoUrl + "/issues",
        prUrl: pr ? pr.html_url : "",
        checking: checking[s.id] || null
      };
    });

    var count = { proved: 0, claimed: 0, open: 0 };
    out.forEach(function (s) { count[s.status]++; });
    return { steps: out, count: count, people: people, openPulls: openPulls };
  }

  function chrome(active) {
    var header = document.getElementById("site-header");
    if (header) {
      var nav = el("nav", { "aria-label": "Site" });
      PAGES.forEach(function (p) {
        var a = link(p[0], p[1]);
        if (p[0] === active) a.setAttribute("aria-current", "page");
        nav.appendChild(a);
      });
      header.className = "top";
      header.appendChild(el("div", { class: "wrap" }, [link("index.html", "qpcp-proofs", "brand"), nav]));
    }
    var footer = document.getElementById("site-footer");
    if (footer) {
      footer.appendChild(el("div", { class: "wrap" }, [
        el("span", { text: "Nothing here is a proof of the conjecture. Each step is checked by Lean against draft definitions." }),
        link(repoUrl, "Source on GitHub"),
        link(repoUrl + "/releases.atom", "Updates feed")
      ]));
    }
  }

  function fail(node) {
    if (node) node.textContent = "Could not load live data from GitHub right now. The repository's issues show the current state.";
  }

  window.QPCP = {
    cfg: CFG, repoUrl: repoUrl, raw: raw, api: api,
    el: el, link: link, getJson: getJson, ago: ago, stepOf: stepOf,
    loadCore: loadCore, chrome: chrome, fail: fail
  };
})();
