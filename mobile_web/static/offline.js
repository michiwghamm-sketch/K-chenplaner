// Offline-Unterstuetzung fuer die mobile Einkaufslisten-Ansicht: schreibende Aktionen (Formulare,
// Haekchen setzen), die wegen fehlender Verbindung fehlschlagen, werden lokal (localStorage)
// zwischengespeichert statt verworfen und automatisch nachgesendet, sobald wieder Netz da ist.
// Ergaenzt sw.js, das die zuletzt besuchten Seiten fuers reine Ansehen offline cacht.
(function () {
  "use strict";

  var QUEUE_KEY = "zk_offline_queue";
  var banner = null;

  function ladeWarteschlange() {
    try {
      return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
    } catch (fehler) {
      return [];
    }
  }

  function schreibeWarteschlange(warteschlange) {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(warteschlange));
    zeigeBanner(warteschlange.length);
  }

  function zeigeBanner(anzahl) {
    if (!banner) return;
    if (anzahl > 0) {
      banner.style.display = "block";
      banner.textContent =
        anzahl === 1
          ? "1 Änderung wird gesendet, sobald wieder Internet da ist …"
          : anzahl + " Änderungen werden gesendet, sobald wieder Internet da ist …";
    } else {
      banner.style.display = "none";
    }
  }

  function zurWarteschlangeHinzufuegen(url, eintraege) {
    var warteschlange = ladeWarteschlange();
    warteschlange.push({ url: url, daten: eintraege, zeit: Date.now() });
    schreibeWarteschlange(warteschlange);
  }

  function formDataZuEintraegen(formData) {
    var eintraege = [];
    formData.forEach(function (wert, schluessel) {
      eintraege.push([schluessel, wert]);
    });
    return eintraege;
  }

  async function sendeEintrag(eintrag) {
    var formData = new FormData();
    eintrag.daten.forEach(function (paar) {
      formData.append(paar[0], paar[1]);
    });
    var antwort = await fetch(eintrag.url, { method: "POST", body: formData });
    // 4xx/5xx (z. B. inzwischen geloeschte Position) nicht endlos wiederholen - nur echte
    // Netzwerkfehler (fetch wirft dann eine Exception, siehe Aufrufer) sollen erneut versucht werden.
    return antwort;
  }

  var wirdGeleert = false;

  async function warteschlangeLeeren() {
    if (wirdGeleert) return;
    var warteschlange = ladeWarteschlange();
    if (warteschlange.length === 0) return;
    wirdGeleert = true;

    var verbleibend = [];
    var mindestensEinErfolg = false;
    for (var i = 0; i < warteschlange.length; i++) {
      try {
        await sendeEintrag(warteschlange[i]);
        mindestensEinErfolg = true;
      } catch (fehler) {
        // Netzwerkfehler - Rest der Warteschlange unveraendert fuer den naechsten Versuch behalten.
        verbleibend = warteschlange.slice(i);
        break;
      }
    }
    schreibeWarteschlange(verbleibend);
    wirdGeleert = false;
    if (mindestensEinErfolg) {
      // Einfacher Reload statt feingranularem DOM-Update - Warteschlangen-Faelle sind selten,
      // der aktuelle Serverstand (inkl. evtl. zwischenzeitlicher Aenderungen anderer) ist danach
      // in jedem Fall korrekt sichtbar.
      window.location.reload();
    }
  }

  function formularAbfangen(form) {
    form.addEventListener("submit", async function (ereignis) {
      if (ereignis.defaultPrevented) return; // vorherige Handler (z. B. Prompt/Confirm) haben abgebrochen
      var bestaetigung = form.dataset.confirm;
      if (bestaetigung && !window.confirm(bestaetigung)) {
        ereignis.preventDefault();
        return;
      }
      ereignis.preventDefault();
      var formData = new FormData(form);
      var button = form.querySelector('button[type="submit"]');
      if (button) button.disabled = true;
      try {
        var antwort = await fetch(form.action, { method: "POST", body: formData });
        if (antwort.redirected) {
          window.location.href = antwort.url;
        } else if (antwort.ok) {
          window.location.reload();
        } else {
          // Serverseitig abgelehnt (z. B. Validierungsfehler, HTTP 400) - Antwort-HTML (enthaelt
          // die Fehlermeldung) direkt anzeigen, genau wie es eine normale Formular-Einreichung
          // ohne JavaScript auch taete, statt sie bei einem blossen Reload zu verlieren.
          var html = await antwort.text();
          document.open();
          document.write(html);
          document.close();
        }
      } catch (fehler) {
        zurWarteschlangeHinzufuegen(form.action, formDataZuEintraegen(formData));
        var hinweis = document.createElement("div");
        hinweis.className = "karte";
        hinweis.style.cssText = "padding:0.7rem 1rem; color:#7a5b00; background:#fff3cd; font-size:0.85rem; margin-top:0.5rem;";
        hinweis.textContent = "Offline gespeichert - wird automatisch gesendet, sobald wieder Verbindung da ist.";
        form.insertAdjacentElement("afterend", hinweis);
        form.reset();
        if (button) button.disabled = false;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    banner = document.getElementById("offline-banner");
    zeigeBanner(ladeWarteschlange().length);
    document.querySelectorAll("form.js-offline-form").forEach(formularAbfangen);
    warteschlangeLeeren();

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(function () {});
    }
  });

  window.addEventListener("online", warteschlangeLeeren);
  setInterval(warteschlangeLeeren, 20000);

  // Von Seiten mit eigener (nicht-generischer) fetch-Logik nutzbar - siehe list_detail.html
  // (Haekchen setzen darf nicht einfach neu geladen werden, das wuerde den Checkbox-Status
  // mitten in der Interaktion durcheinanderbringen).
  window.zkQueueRequest = zurWarteschlangeHinzufuegen;
  window.zkFormDataZuEintraegen = formDataZuEintraegen;
})();
