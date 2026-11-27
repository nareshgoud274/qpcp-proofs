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
  // Agents are told to fetch JOIN.md at this fixed commit, never from main
  // (MAINTAINERS.md, "Updating JOIN.md"). Keep it equal to the pin in README.md.
  var JOIN_COMMIT = "41fb85b98589e7f1b758764ef5ed29e4f706ca38";
  var joinUrl = "https://raw.githubusercontent.com/" + CFG.owner + "/" + CFG.repo + "/" + JOIN_COMMIT + "/JOIN.md";
  var api = "https://api.github.com/repos/" + CFG.owner + "/" + CFG.repo;
  // One prebuilt file with everything the site shows, rebuilt by the `status`
  // workflow. Reading it costs no GitHub API calls, so any number of visitors
  // can watch. Its verdicts come only from the latest verification record. If
  // it is missing, the pages fall back to the API, which can show claims and
  // open steps but never a verdict: verification status is then unavailable.
  var siteData = "https://raw.githubusercontent.com/" + CFG.owner + "/" + CFG.repo + "/site-data/";
  var statusUrl = siteData + "status.json";

  var PAGES = [
    ["index.html", "Map"],
    ["programs.html", "Programs"],
    ["live.html", "Live"],
    ["updates.html", "Updates"],
    ["reports.html", "Reports"],
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
    var m = /\b(S\d{3,6}|L\d{1,9})\b/.exec(title || "");
    return m ? m[1] : null;
  }

  function loadStatus(maxAgeMs) {
    return getJson(statusUrl, maxAgeMs === undefined ? 60000 : maxAgeMs).then(function (s) {
      if (!s || !Array.isArray(s.steps) || !s.count) throw new Error("bad status file");
      return s;
    });
  }

  /* The same rule as build_status.py, applied again to whatever feed arrives: a
     step is proved or refuted now only if the feed names the verified file on
     main (`verified`). Anything else is shown as "unknown" and taken out of the
     counts, overall and per program, and out of that person's proved and refuted
     lists, so no page can show a verdict without it. */
  function enforceVerified(s) {
    var byProgram = {};
    (s.programs || []).forEach(function (p) { byProgram[p.id] = p; });
    s.steps.forEach(function (st) {
      if ((st.status === "proved" || st.status === "refuted") && !(st.verified && st.verified.path && st.verified.blob)) {
        var was = st.status;
        st.status = "unknown";
        s.count[was] = Math.max(0, (s.count[was] || 0) - 1);
        s.count.unknown = (s.count.unknown || 0) + 1;
        var p = byProgram[st.program];
        if (p && p.count) {
          p.count[was] = Math.max(0, (p.count[was] || 0) - 1);
          p.count.unknown = (p.count.unknown || 0) + 1;
        }
        // ...and from every person's list, so the contributors page agrees with the counts.
        Object.keys(s.people || {}).forEach(function (who) {
          var lists = s.people[who];
          if (lists && Array.isArray(lists[was])) lists[was] = lists[was].filter(function (id) { return id !== st.id; });
        });
      }
    });
    return s;
  }

  /* Loads the step list and its live status. maxAgeMs controls cache reuse. */
  function loadCore(maxAgeMs) {
    return loadStatus(maxAgeMs).then(enforceVerified).then(function (s) {
      s.steps.forEach(function (st) { if (!st.url) st.url = repoUrl + "/issues"; });
      return {
        steps: s.steps, count: s.count, people: s.people || {},
        openPulls: (s.openPulls || []).map(function (p) {
          return { title: p.title, html_url: p.url, created_at: p.created_at, user: { login: p.user } };
        }),
        openPullCount: s.openPullCount || 0,
        programs: s.programs || [], proposals: s.proposals || [],
        mandates: s.mandates || [], barriers: s.barriers || [],
        verification: s.verification || { available: false },
        accepting: s.accepting || null,
        generatedAt: s.generated_at
      };
    }).catch(function () { return loadCoreFromApi(maxAgeMs); });
  }

  function loadCoreFromApi(maxAgeMs) {
    var age = maxAgeMs === undefined ? 120000 : maxAgeMs;
    return getJson(raw + "steps.json", 600000).then(function (steps) {
      return Promise.all([
        getPaged(api + "/issues?labels=step&state=all", age, 10),
        // Credit is never guessed from titles (#115): without the feed, no pull request is credited.
        Promise.resolve([]),
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

    // closedPulls is ignored: credit comes only from the feed, which takes it
    // from the commit that added each file (#115), never from a title.

    var checking = {};
    openPulls.forEach(function (p) {
      var id = stepOf(p.title);
      if (id) checking[id] = p;
    });

    var people = {};
    var out = steps.map(function (s) {
      var issue = issueBy[s.id];
      var status = "open", who = "", when = "";
      var has = function (name) {
        return !!issue && (issue.labels || []).some(function (l) { return l.name === name; });
      };
      if (s.retired) {
        status = "retired";
        when = issue ? issue.closed_at || issue.updated_at : "";
      } else if (issue && issue.state === "closed") {
        // A closed issue is not a verdict: it may be proved, superseded or
        // abandoned. Only the verification record says which (#113).
        status = "unknown";
      } else if (has("claimed")) {
        status = "claimed";
        who = (issue.assignees || []).map(function (a) { return a.login; }).join(", ");
        when = issue.updated_at;
      }
      return {
        id: s.id, title: s.title, section: s.section, difficulty: s.difficulty, deps: s.deps || [],
        status: status, who: who, when: when,
        disputed: !s.retired && has("disputed"), replacedBy: s.replaced_by || "",
        url: issue ? issue.html_url : repoUrl + "/issues",
        prUrl: "",
        checking: checking[s.id] || null
      };
    });

    var count = { proved: 0, refuted: 0, pending: 0, unknown: 0, claimed: 0, open: 0, retired: 0, disputed: 0, proposals: 0 };
    out.forEach(function (s) {
      count[s.status]++;
      if (s.disputed) count.disputed++;
    });
    return { steps: out, count: count, people: people, openPulls: openPulls, openPullCount: openPulls.length, programs: [], proposals: [], mandates: [], barriers: [],
             verification: { available: false }, generatedAt: "" };
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

  /* Reports, newest first: {step, summary, verdict, user, when, url}. */
  function loadReports() {
    return loadStatus().then(function (s) {
      return {
        retired: s.count.retired || 0, generatedAt: s.generated_at,
        reports: (s.reports || []).map(function (r) {
          return { step: r.step, summary: r.summary, verdict: r.verdict, user: r.user, when: r.closed_at || r.created_at, url: r.url };
        })
      };
    }).catch(function () {
      return Promise.all([
        getPaged(api + "/issues?labels=report&state=all", 120000, 10),
        getJson(raw + "steps.json", 600000)
      ]).then(function (res) {
        var has = function (i, n) { return (i.labels || []).some(function (l) { return l.name === n; }); };
        return {
          retired: res[1].filter(function (s) { return s.retired; }).length, generatedAt: "",
          reports: res[0].filter(function (i) { return !i.pull_request; }).map(function (i) {
            var t = String(i.title || "");
            return {
              step: stepOf(t) || "", summary: t.replace(/^\s*Report\s+S\d{3,6}\s*:?\s*/i, "") || "(no summary)",
              verdict: i.state === "open" ? "open" : has(i, "confirmed") ? "confirmed" : has(i, "dismissed") ? "dismissed" : "unresolved",
              user: i.user ? i.user.login : "", when: i.closed_at || i.created_at, url: i.html_url
            };
          })
        };
      });
    });
  }

  function loadReleases() {
    return loadStatus().then(function (s) { return s.releases || []; }).catch(function () {
      return getJson(api + "/releases?per_page=30", 120000).then(function (rels) {
        return rels.filter(function (r) { return !r.draft; }).map(function (r) {
          return { name: r.name || r.tag_name, tag: r.tag_name, published_at: r.published_at, body: r.body || "", url: r.html_url };
        });
      });
    });
  }

  /* "Record as of 3 min ago" when reading the prebuilt file, else the read time. */
  function stamp(generatedAt) {
    return generatedAt ? "Record as of " + ago(generatedAt) + "." : "Live from GitHub, read " + new Date().toLocaleTimeString() + ".";
  }

  /* One line on what the verdicts rest on. */
  function verificationLine(v) {
    if (!v || !v.available) return "Verification status unavailable: no verdict is shown until the verification record can be read.";
    var line = "Verdicts are from the verification of commit " + v.commit.slice(0, 7) + " (" + ago(v.verifiedAt) + ").";
    if (!v.current) line += " Newer commits of main are not verified yet; their results show as pending.";
    return line;
  }

  function stepUrl(id) { return "step.html?id=" + encodeURIComponent(id); }

  function fail(node) {
    if (node) node.textContent = "Could not load live data from GitHub right now. The repository's issues show the current state.";
  }

  window.QPCP = {
    cfg: CFG, repoUrl: repoUrl, raw: raw, siteData: siteData, joinUrl: joinUrl, api: api,
    el: el, link: link, getJson: getJson, getPaged: getPaged, ago: ago, stepOf: stepOf, stepUrl: stepUrl,
    loadCore: loadCore, loadReports: loadReports, loadReleases: loadReleases, stamp: stamp, chrome: chrome, fail: fail,
    verificationLine: verificationLine,
    // For tests/test_site_fallback.py: the builder the pages use when the feed is unavailable.
    _buildFromApi: build,
    _enforceVerified: enforceVerified
  };
})();
