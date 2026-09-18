/* Interface de pilotage. Vanilla JS volontairement : l'ecran se resume a une
   liste, un panneau de detail et une navigation. Un framework imposerait une
   chaine de build pour un outil local mono-utilisateur. */

const etat = {
  vue: "a_valider",
  vues: [],
  offres: [],
  choisie: null,
  parametres: null,
  sondage: null,     // identifiant du setInterval de suivi de tache
};

const $ = (sel) => document.querySelector(sel);

/* Vues ou l'offre a ete ecartee : on y propose de la ramener a la main. La
   recuperation pose un verrou en base, sinon le prochain rescore la
   reecarterait par le filtre meme qui l'avait sortie. */
const REBUTS = ["ecarte", "hors_cible", "sans_canal", "ecole"];

// ---------------------------------------------------------------- utilitaires

async function api(chemin, options = {}) {
  const reponse = await fetch(chemin, options);
  const corps = await reponse.json().catch(() => ({}));
  if (!reponse.ok) throw new Error(corps.erreur || `HTTP ${reponse.status}`);
  return corps;
}

let minuteurToast;
function toast(message, erreur = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("erreur", erreur);
  el.classList.add("visible");
  clearTimeout(minuteurToast);
  minuteurToast = setTimeout(() => el.classList.remove("visible"), 3200);
}

/* Monogramme colore, utilise quand la source ne fournit pas de logo (LBA).
   La teinte derive du nom : la meme entreprise garde toujours la meme couleur,
   ce qui aide a la reconnaitre d'une vue a l'autre. */
function monogramme(nom) {
  const propre = (nom || "?").replace(/[^A-Za-zÀ-ÿ0-9 ]/g, " ").trim();
  const mots = propre.split(/\s+/).filter(Boolean);
  const initiales = (mots.length > 1
    ? mots[0][0] + mots[1][0]
    : (propre.slice(0, 2) || "?")).toUpperCase();
  let somme = 0;
  for (const c of propre) somme = (somme * 31 + c.charCodeAt(0)) % 360;
  return { initiales, fond: `hsl(${somme} 52% 46%)` };
}

function gabaritLogo(offre) {
  if (offre.logo_url) {
    return `<div class="logo"><img src="${offre.logo_url}" alt=""
              onerror="this.parentElement.innerHTML='';this.parentElement.style.background='${monogramme(offre.entreprise).fond}';this.parentElement.textContent='${monogramme(offre.entreprise).initiales}'"></div>`;
  }
  const m = monogramme(offre.entreprise);
  return `<div class="logo" style="background:${m.fond};border-color:transparent">${m.initiales}</div>`;
}

/* Seuils de lecture : au-dela de 80 l'offre passe en premier, en dessous de
   65 elle est limite. C'est la seule information que porte cette couleur. */
function classeAdequation(n) {
  if (n >= 80) return "forte";
  if (n >= 65) return "moyenne";
  return "faible";
}

// ---------------------------------------------------------------- navigation

function rendreNav() {
  const groupes = { tri: "#nav-tri", pipeline: "#nav-pipeline", rebut: "#nav-rebut" };
  for (const [groupe, selecteur] of Object.entries(groupes)) {
    const conteneur = $(selecteur);
    const titre = conteneur.querySelector(".nav-titre");
    conteneur.innerHTML = "";
    conteneur.appendChild(titre);
    etat.vues.filter((v) => v.groupe === groupe).forEach((v) => {
      const b = document.createElement("button");
      b.className = "nav-item" + (v.cle === etat.vue ? " actif" : "");
      b.innerHTML = `<span class="point ${v.couleur}"></span>
                     <span>${v.titre}</span>
                     <span class="n">${v.compte}</span>`;
      b.onclick = () => changerVue(v.cle);
      conteneur.appendChild(b);
    });
  }
}

function changerVue(cle) {
  etat.vue = cle;
  etat.choisie = null;
  $("#contenu").classList.remove("avec-detail");

  // Les parametres ne sont pas une vue d'offres : la liste, la barre de
  // lancement et les actions globales n'ont aucun sens dessus.
  const reglages = cle === "parametres";
  $("#page-parametres").hidden = !reglages;
  $("#contenu").hidden = reglages;
  $("#lancement").hidden = reglages;
  $("#compte-vue").hidden = reglages;
  $("#btn-lettres").hidden = reglages;
  $("#btn-postuler").hidden = reglages;
  $("#nav-parametres").classList.toggle("actif", reglages);

  if (reglages) {
    $("#titre-vue").textContent = "Paramètres";
    rendreNav();
    return chargerParametres();
  }

  const vue = etat.vues.find((v) => v.cle === cle);
  $("#titre-vue").textContent = vue ? vue.titre : cle;
  rendreNav();
  chargerOffres();
}

// ---------------------------------------------------------------- liste

async function chargerOffres() {
  // "parametres" n'est pas un statut : la tache qui se termine pendant qu'on
  // est sur cette page ne doit pas declencher une requete invalide.
  if (etat.vue === "parametres") return;
  etat.offres = await api(`/api/offres?statut=${etat.vue}`);
  $("#compte-vue").textContent =
    `${etat.offres.length} offre${etat.offres.length > 1 ? "s" : ""}`;
  rendreListe();
}

function rendreListe() {
  const liste = $("#liste");
  if (!etat.offres.length) {
    liste.innerHTML = `<div class="vide">
      <div class="grand">∅</div>
      <div>Aucune offre dans cette vue.</div></div>`;
    return;
  }

  liste.innerHTML = etat.offres.map((o) => {
    const distance = o.distance_km != null
      ? `<span class="n">${o.distance_km}</span> km` : "distance inconnue";
    const cles = (o.mots_cles || []).length
      ? o.mots_cles.map((m) => `<span class="cle">${m}</span>`).join("")
      : `<span class="cle faible">${o.naf || "secteur non précisé"}</span>`;
    return `
      <article class="offre ${etat.choisie === o.id ? "choisie" : ""}" data-id="${o.id}">
        ${gabaritLogo(o)}
        <div class="corps">
          <div class="intitule">${o.intitule || "(sans intitulé)"}</div>
          <div class="ligne-meta">${o.entreprise || "employeur non communiqué"}<span
            class="sep">/</span><span class="lieu">${o.lieu || "lieu inconnu"} · ${distance}</span></div>
          <div class="cles">${cles}</div>
        </div>
        <div class="adequation ${classeAdequation(o.matching)}">
          <div class="valeur n">${o.matching}%</div>
          <div class="mot">adéquation</div>
        </div>
      </article>`;
  }).join("");

  liste.querySelectorAll(".offre").forEach((el) => {
    el.onclick = () => ouvrirDetail(Number(el.dataset.id));
  });
}

// ---------------------------------------------------------------- detail

const LIBELLES_AXES = {
  technique: "Technique", nature: "Poste", proximite: "Distance",
  structure: "Structure", conditions: "Conditions",
};

async function ouvrirDetail(id) {
  etat.choisie = id;
  rendreListe();
  $("#contenu").classList.add("avec-detail");

  const o = await api(`/api/offre/${id}`);
  const axes = Object.entries(o.ventilation || {})
    .sort(([a], [b]) => Object.keys(LIBELLES_AXES).indexOf(a) -
                        Object.keys(LIBELLES_AXES).indexOf(b))
    .map(([k, n]) => `<div class="axe"><i>${LIBELLES_AXES[k] || k}</i>
        <span class="jauge"><b style="width:${n}%"></b></span><u>${n}</u></div>`)
    .join("");

  const lien = o.url_candidature
    ? `<a class="bouton" href="${o.url_candidature}" target="_blank" rel="noopener">Ouvrir l'offre</a>`
    : "";

  $("#detail").innerHTML = `
    <div class="haut">
      ${gabaritLogo(o)}
      <div>
        <h3>${o.intitule || "(sans intitulé)"}</h3>
        <div class="meta">${o.entreprise || "employeur non communiqué"}</div>
        <div class="meta">${o.lieu || ""}${o.distance_km != null ? " · " + o.distance_km + " km" : ""}</div>
      </div>
    </div>

    ${o.motif ? `<div class="arbitrage motif"><b>Écartée :</b> ${o.motif}</div>` : ""}
    ${o.doute ? `<div class="arbitrage"><b>À arbitrer :</b> ${o.doute}</div>` : ""}

    <div class="section">
      <h4>Adéquation ${o.matching}%</h4>
      <div class="axes">${axes}</div>
    </div>

    <div class="section">
      <h4>Correspondances avec le CV</h4>
      <div class="cles">${(o.mots_cles || []).map((m) =>
        `<span class="cle">${m}</span>`).join("") || "<span class='cle faible'>aucune</span>"}</div>
    </div>

    <div class="section">
      <h4>Contrat</h4>
      <p>${o.contrat_type || "non précisé"}${o.contrat_duree ? ` · ${o.contrat_duree} mois` : ""}
         · ${o.genre === "spontanee" ? "candidature spontanée" : "offre publiée"}
         · source ${o.source}</p>
    </div>

    ${o.description ? `<div class="section"><h4>Annonce</h4>
      <div class="extrait">${o.description.slice(0, 4000)}</div></div>` : ""}

    ${o.lettre ? `<div class="section"><h4>Lettre générée</h4>
      <div class="extrait">${o.lettre}</div></div>` : ""}

    <div class="actions">
      ${etat.vue === "a_valider"
        ? `<button class="bouton primaire" data-action="valide_manuel">Valider</button>`
        : ""}
      ${REBUTS.includes(etat.vue)
        ? `<button class="bouton primaire" data-action="recuperer">Récupérer dans le vivier</button>`
        : ""}
      ${lien}
      <button class="bouton retrait" data-action="retirer">Retirer de la liste</button>
    </div>`;

  $("#detail").querySelectorAll("[data-action]").forEach((b) => {
    b.onclick = () => changerStatut(id, b.dataset.action);
  });
  // Le panneau ne doit pas se refermer quand on clique a l'interieur
  $("#detail").onclick = (e) => e.stopPropagation();
}

async function changerStatut(id, action) {
  const statut = action === "retirer" ? "rejete_manuel" : action;
  try {
    await api(`/api/offre/${id}/statut`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ statut }),
    });
    toast(action === "retirer" ? "Offre retirée"
        : action === "recuperer" ? "Offre récupérée dans le vivier"
        : "Offre validée");
    etat.choisie = null;
    $("#contenu").classList.remove("avec-detail");
    await Promise.all([chargerOffres(), rafraichirComptes()]);
  } catch (e) {
    toast(e.message, true);
  }
}

// ---------------------------------------------------------------- CV, adresse

function fermerDetail() {
  etat.choisie = null;
  $("#contenu").classList.remove("avec-detail");
  rendreListe();
}

function brancherDepot() {
  const depot = $("#depot");
  const champ = $("#cv-fichier");

  depot.onclick = () => champ.click();
  champ.onchange = () => champ.files[0] && televerserCV(champ.files[0]);

  ["dragenter", "dragover"].forEach((evt) =>
    depot.addEventListener(evt, (e) => {
      e.preventDefault();
      depot.classList.add("survol");
    }));
  ["dragleave", "drop"].forEach((evt) =>
    depot.addEventListener(evt, (e) => {
      e.preventDefault();
      depot.classList.remove("survol");
    }));
  depot.addEventListener("drop", (e) => {
    const fichier = e.dataTransfer.files[0];
    if (fichier) televerserCV(fichier);
  });
}

function afficherCV(cv) {
  const nom = cv.present ? cv.nom : "Aucun CV";
  $("#cv-nom").textContent = nom;
  $("#cv-info").textContent = cv.present
    ? `${cv.taille_ko} Ko`
    : "à déposer dans les paramètres";
  if ($("#p-cv-nom")) {
    $("#p-cv-nom").textContent = nom;
    $("#p-cv-info").textContent = cv.present
      ? `${cv.taille_ko} Ko · glissez pour remplacer`
      : "Glissez un PDF ou cliquez";
  }
}

async function televerserCV(fichier) {
  if (!fichier.name.toLowerCase().endsWith(".pdf")) {
    return toast("Le CV doit être un PDF", true);
  }
  const donnees = new FormData();
  donnees.append("fichier", fichier);
  try {
    const r = await api("/api/cv", { method: "POST", body: donnees });
    afficherCV({ present: true, nom: r.nom, taille_ko: r.taille_ko });
    toast("CV mis à jour, l'ancien est archivé");
  } catch (e) {
    toast(e.message, true);
  }
}

async function enregistrerRecherche() {
  const adresse = $("#adresse").value.trim();
  const rayon = Number($("#rayon").value);
  if (!adresse && !rayon) return true;
  try {
    const r = await api("/api/parametres", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ adresse, rayon_km: rayon || null }),
    });
    $("#adresse").value = r.adresse;
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  }
}

// ---------------------------------------------------------------- parametres

async function chargerParametres() {
  const p = await api("/api/parametres");
  etat.parametres = p;

  $("#cherche-alternance").checked = !!p.recherche_alternance;
  $("#cherche-stages").checked = !!p.recherche_stages;
  $("#duree-stage").value = p.stage_duree_semaines;
  $("#ecart-court").value = p.stage_ecart_court;
  $("#ecart-long").value = p.stage_ecart_long;
  majNatures();

  $("#p-adresse").value = p.adresse || "";
  $("#p-rayon").value = p.rayon_km;
  $("#p-seuil").value = p.seuil_matching;
  $("#p-duree").value = p.duree_max_mois;
  $("#p-prime").value = p.prime_grand_groupe;
  $("#termes").value = (p.exclusions_perso || []).join("\n");
  $("#termes-souples").value = (p.exclusions_perso_souples || []).join("\n");
  $("#impact").innerHTML = "";

  afficherCV(p.cv);
  $("#etat-jeton").textContent = p.jeton.present
    ? `Jeton enregistré (${p.jeton.longueur} caractères, ${p.jeton.empreinte})`
    : "Aucun jeton : la génération des lettres échouera.";
  $("#etat-jeton").classList.toggle("manquant", !p.jeton.present);

  $("#exclusions").innerHTML = p.groupes.map((g) => `
    <label class="exclusion${g.actif ? " active" : ""}" data-cle="${g.cle}">
      <input type="checkbox" ${g.actif ? "checked" : ""}>
      <span class="corps">
        <span class="titre">${g.libelle}</span>
        <span class="exemples">${g.exemples}</span>
      </span>
      <span class="n">${g.motifs}</span>
    </label>`).join("");

  $("#exclusions").querySelectorAll(".exclusion").forEach((el) => {
    el.querySelector("input").onchange = (e) =>
      el.classList.toggle("active", e.target.checked);
  });

  // Les champs d'ajout ne sont pas des donnees : les vider evite qu'une saisie
  // abandonnee reapparaisse au prochain passage sur la page.
  ["#rome-nouveau", "#mot-nouveau", "#poids-nouveau", "#ecole-nouvelle"]
    .forEach((s) => { $(s).value = ""; });

  rendreComptes();
  rendreProfil(p);
  rendreRomes(p);
  rendreMotsCles(p);
  rendreBlocklist(p);
}

/* Les champs du profil sont decrits ici et non dans le HTML : l'ordre et les
   libelles changent plus souvent que la structure, et une seule source evite
   qu'un champ soit affiche sans jamais etre renvoye au serveur. */
const CHAMPS_PROFIL = [
  ["nom", "Nom complet"],
  ["email", "Email"],
  ["telephone_affiche", "Téléphone affiché"],
  ["telephone", "Téléphone (format international)"],
  ["ville", "Ville affichée"],
  ["formation", "Formation"],
  ["etablissement", "Établissement"],
  ["debut", "Disponibilité"],
  ["fin", "Fin de contrat visée"],
  ["duree_mois", "Durée cible (mois)"],
  ["rythme", "Rythme d'alternance"],
  ["poursuite_etudes", "Poursuite d'études"],
];

async function rendreComptes() {
  const comptes = await api("/api/comptes");
  $("#comptes").innerHTML = comptes.map((c) => `
    <div class="compte-site${c.connecte ? " ok" : ""}" data-cle="${c.cle}">
      <div class="corps">
        <div class="titre">${c.libelle}</div>
        <div class="role">${c.role}</div>
      </div>
      <div class="etat-compte">${c.connecte
        ? `<span class="n">${c.cookies}</span> cookies · ${c.age_jours} j`
        : "non connecté"}</div>
      <button class="bouton" data-connecter="${c.cle}">${
        c.connecte ? "Reconnecter" : "Connecter"}</button>
      ${c.connecte
        ? `<button class="bouton retrait" data-oublier="${c.cle}">Oublier</button>`
        : ""}
    </div>`).join("");

  $("#comptes").querySelectorAll("[data-connecter]").forEach((b) => {
    b.onclick = () => {
      toast("Connecte-toi dans la fenêtre par email et mot de passe", false);
      lancerTache("connexion", { site: b.dataset.connecter });
    };
  });
  $("#comptes").querySelectorAll("[data-oublier]").forEach((b) => {
    b.onclick = async () => {
      if (!confirm("Supprimer la session enregistrée ? Tu devras te reconnecter "
                 + "pour déposer une candidature sur ce site.")) return;
      await api(`/api/comptes/${b.dataset.oublier}`, { method: "DELETE" });
      rendreComptes();
      toast("Session supprimée");
    };
  });
}

/* La duree de stage n'a de sens que si les stages sont cherches : l'afficher
   en permanence laisserait croire qu'elle s'applique a l'alternance. */
function majNatures() {
  const stages = $("#cherche-stages").checked;
  $("#champ-duree-stage").hidden = !stages;
  document.querySelectorAll(".nature").forEach((el) => {
    el.classList.toggle("active", el.querySelector("input").checked);
  });
}

function rendreProfil(p) {
  $("#grille-profil").innerHTML = CHAMPS_PROFIL.map(([cle, libelle]) => {
    const valeur = p.profil[cle] ?? "";
    const nombre = typeof valeur === "number";
    const long = String(valeur).length > 60;
    const saisie = long
      ? `<textarea data-profil="${cle}" rows="2">${valeur}</textarea>`
      : `<input type="${nombre ? "number" : "text"}" data-profil="${cle}"
                value="${String(valeur).replace(/"/g, "&quot;")}">`;
    return `<div class="champ"><label>${libelle}</label>${saisie}</div>`;
  }).join("");
}

function rendreRomes(p) {
  $("#romes").innerHTML = p.romes.map((code) => `
    <span class="etiquette" data-valeur="${code}">
      <b class="n">${code}</b>
      <i>${p.romes_connus[code] || "libellé inconnu"}</i>
      <button title="Retirer">×</button>
    </span>`).join("") || "<span class='vide-liste'>aucun code</span>";

  const absents = Object.entries(p.romes_connus).filter(([c]) => !p.romes.includes(c));
  $("#rome-suggestions").innerHTML = absents.length
    ? "Non collectés : " + absents.map(([c, l]) =>
        `<button class="suggestion" data-rome="${c}">${c} ${l}</button>`).join("")
    : "";
  $("#rome-suggestions").querySelectorAll(".suggestion").forEach((b) => {
    b.onclick = () => { ajouterRome(b.dataset.rome); };
  });
  brancherRetraits("#romes");
}

function rendreMotsCles(p) {
  const entrees = Object.entries(p.mots_cles).sort((a, b) => b[1] - a[1]);
  $("#mots-cles").innerHTML = entrees.map(([mot, poids]) => `
    <span class="etiquette" data-valeur="${mot}" data-poids="${poids}">
      <span>${mot}</span>
      <b class="n">${poids}</b>
      <button title="Retirer">×</button>
    </span>`).join("");
  brancherRetraits("#mots-cles");
}

function rendreBlocklist(p) {
  $("#blocklist").innerHTML = p.ecole_blocklist.map((nom) => `
    <span class="etiquette" data-valeur="${nom}">
      <span>${nom}</span>
      <button title="Retirer">×</button>
    </span>`).join("") || "<span class='vide-liste'>aucun organisme</span>";
  brancherRetraits("#blocklist");
}

/* Le retrait est purement local : rien n'est enregistre tant que le bouton
   Enregistrer n'a pas ete presse, ce qui laisse revenir en arriere en
   rechargeant la page. */
function brancherRetraits(selecteur) {
  $(selecteur).querySelectorAll(".etiquette button").forEach((b) => {
    b.onclick = () => b.closest(".etiquette").remove();
  });
}

function ajouterEtiquette(selecteur, html) {
  $(selecteur).insertAdjacentHTML("beforeend", html);
  brancherRetraits(selecteur);
}

function ajouterRome(code) {
  code = code.trim().toUpperCase();
  if (!/^[A-Z][0-9]{4}$/.test(code)) return toast("Format attendu : M1805", true);
  if (lireEtiquettes("#romes").includes(code)) return toast("Déjà présent");
  const libelle = (etat.parametres.romes_connus || {})[code] || "libellé inconnu";
  ajouterEtiquette("#romes", `<span class="etiquette" data-valeur="${code}">
      <b class="n">${code}</b><i>${libelle}</i><button title="Retirer">×</button></span>`);
}

function lireEtiquettes(selecteur) {
  return [...$(selecteur).querySelectorAll(".etiquette")].map((e) => e.dataset.valeur);
}

function lireMotsCles() {
  const mots = {};
  $("#mots-cles").querySelectorAll(".etiquette").forEach((e) => {
    mots[e.dataset.valeur] = Number(e.dataset.poids);
  });
  return mots;
}

function lireProfil() {
  const profil = {};
  $("#grille-profil").querySelectorAll("[data-profil]").forEach((el) => {
    profil[el.dataset.profil] = el.type === "number" ? Number(el.value) : el.value.trim();
  });
  return profil;
}

async function retablirDefaut(cle) {
  try {
    await api(`/api/parametres/defaut/${cle}`, { method: "POST" });
    await chargerParametres();
    toast("Valeurs par défaut rétablies");
  } catch (e) {
    toast(e.message, true);
  }
}

async function enregistrerParametres() {
  const exclusions = {};
  $("#exclusions").querySelectorAll(".exclusion").forEach((el) => {
    exclusions[el.dataset.cle] = el.querySelector("input").checked;
  });

  const charge = {
    adresse: $("#p-adresse").value.trim(),
    rayon_km: Number($("#p-rayon").value) || null,
    seuil_matching: Number($("#p-seuil").value),
    recherche_alternance: $("#cherche-alternance").checked,
    recherche_stages: $("#cherche-stages").checked,
    stage_duree_semaines: Number($("#duree-stage").value) || null,
    stage_ecart_court: Number($("#ecart-court").value),
    stage_ecart_long: Number($("#ecart-long").value),
    duree_max_mois: Number($("#p-duree").value) || null,
    prime_grand_groupe: Number($("#p-prime").value),
    exclusions,
    exclusions_perso: lignes("#termes"),
    exclusions_perso_souples: lignes("#termes-souples"),
    profil: lireProfil(),
    romes: lireEtiquettes("#romes"),
    mots_cles: lireMotsCles(),
    ecole_blocklist: lireEtiquettes("#blocklist"),
  };

  try {
    const r = await api("/api/parametres", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(charge),
    });
    $("#adresse").value = r.adresse;
    $("#rayon").value = r.rayon_km;
    $("#sous-titre").textContent = `seuil d'adéquation ${r.seuil_matching}%`;
    $("#etat-parametres").textContent =
      "Enregistré. Recalculez les scores pour l'appliquer aux offres déjà collectées.";
    toast("Paramètres enregistrés");
  } catch (e) {
    toast(e.message, true);
  }
}

function lignes(selecteur) {
  return $(selecteur).value.split("\n").map((t) => t.trim()).filter(Boolean);
}

/* Simulation : ce que la configuration en cours de saisie couperait sur les
   offres deja collectees. Rien n'est enregistre. C'est le garde-fou contre le
   terme trop large qui emporte une offre qu'on voulait garder. */
async function montrerImpact() {
  const zone = $("#impact");
  zone.innerHTML = "<div class='ligne-impact'>Analyse en cours…</div>";

  const exclusions = {};
  $("#exclusions").querySelectorAll(".exclusion").forEach((el) => {
    exclusions[el.dataset.cle] = el.querySelector("input").checked;
  });

  try {
    const r = await api("/api/parametres/impact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        exclusions,
        exclusions_perso: lignes("#termes"),
        exclusions_perso_souples: lignes("#termes-souples"),
      }),
    });

    if (!r.impacts.length) {
      zone.innerHTML = `<div class="ligne-impact">Aucune des ${r.analysees}
        offres publiées déjà collectées ne serait écartée.</div>`;
      return;
    }

    zone.innerHTML = `<div class="ligne-impact">Sur ${r.analysees} offres
      publiées en base :</div>` + r.impacts.map((i) => `
      <div class="impact-bloc${i.actionnables ? " alerte" : ""}">
        <div class="tete">
          <span class="quoi">${i.libelle}</span>
          <span class="mode">${i.levable ? "levable" : "strict"}</span>
          <span class="n">${i.total}</span>
        </div>
        ${i.actionnables ? `<div class="avertit">dont
          <span class="n">${i.actionnables}</span> actuellement dans ton vivier</div>` : ""}
        <ul>${i.exemples.map((e) => `<li>
          <span class="n">${e.matching}%</span>
          <span class="${e.vivier ? "vivier" : ""}">${e.intitule}</span></li>`).join("")}</ul>
      </div>`).join("");
  } catch (e) {
    zone.innerHTML = "";
    toast(e.message, true);
  }
}

async function enregistrerJeton() {
  const jeton = $("#jeton").value.trim();
  if (!jeton) return toast("Champ vide", true);
  try {
    const r = await api("/api/parametres/jeton", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jeton }),
    });
    $("#jeton").value = "";
    $("#etat-jeton").textContent =
      `Jeton enregistré (${r.jeton.longueur} caractères, ${r.jeton.empreinte})`;
    $("#etat-jeton").classList.remove("manquant");
    toast("Jeton enregistré dans .env");
  } catch (e) {
    toast(e.message, true);
  }
}

// ---------------------------------------------------------------- taches

const TITRES_TACHE = {
  collecte: "Collecte des offres",
  lettres: "Génération des lettres",
  candidatures: "Dépôt des candidatures",
  connexion: "Connexion à un site",
  rescore: "Recalcul des scores",
  reconnaissance: "Inspection des formulaires",
};

async function lancerTache(type, extra = {}) {
  try {
    await api("/api/tache", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, ...extra }),
    });
    demarrerSondage();
  } catch (e) {
    toast(e.message, true);
  }
}

function demarrerSondage() {
  if (etat.sondage) return;
  etat.sondage = setInterval(sonder, 1200);
  sonder();
}

async function sonder() {
  let r;
  try {
    r = await api("/api/tache");
  } catch { return; }

  const t = r.tache;
  const panneau = $("#progression");

  if (!t) { panneau.hidden = true; return; }

  panneau.hidden = false;
  panneau.className = "progression" + (t.statut === "terminee" ? " terminee"
                                     : t.statut === "echouee" ? " echouee" : "");
  $("#prog-titre").textContent = TITRES_TACHE[t.type] || t.type;
  $("#prog-detail").textContent = t.total
    ? `${t.progression} / ${t.total}`
    : (t.statut === "en_cours" ? "en cours" : t.statut);
  const part = t.total ? Math.min(100, 100 * t.progression / t.total)
                       : (t.statut === "en_cours" ? 35 : 100);
  $("#prog-barre").style.width = part + "%";
  $("#prog-ligne").textContent = t.message || "";

  // Comptes de la navigation, mis a jour en direct pendant la tache
  etat.vues = etat.vues.map((v) => ({ ...v, compte: r.compte[v.cle] ?? v.compte }));
  rendreNav();

  if (t.statut !== "en_cours") {
    clearInterval(etat.sondage);
    etat.sondage = null;
    majBoutons(false);
    chargerOffres();
    if (t.type === "connexion" && !$("#page-parametres").hidden) rendreComptes();
    toast(t.statut === "terminee"
      ? `${TITRES_TACHE[t.type] || t.type} : terminé`
      : `Échec : ${t.message}`, t.statut !== "terminee");
    setTimeout(() => { panneau.hidden = true; }, 6000);
  } else {
    majBoutons(true);
  }
}

function majBoutons(occupe) {
  ["#btn-collecte", "#btn-lettres", "#btn-postuler", "#btn-rescore",
   "#btn-reconnaissance"].forEach((s) => {
    $(s).disabled = occupe;
  });
}

async function rafraichirComptes() {
  const r = await api("/api/tache");
  etat.vues = etat.vues.map((v) => ({ ...v, compte: r.compte[v.cle] ?? v.compte }));
  rendreNav();
}

// ---------------------------------------------------------------- demarrage

async function demarrer() {
  const ctx = await api("/api/contexte");
  etat.vues = ctx.vues;

  $("#nom-profil").textContent = ctx.profil.nom;
  $("#sous-titre").textContent = `seuil d'adéquation ${ctx.profil.seuil}%`;
  $("#adresse").value = ctx.profil.adresse || "";
  $("#rayon").value = ctx.profil.rayon || 35;

  afficherCV(ctx.cv);
  brancherDepot();

  $("#nav-parametres").onclick = () => changerVue("parametres");
  $("#btn-parametres").onclick = enregistrerParametres;
  $("#btn-jeton").onclick = enregistrerJeton;
  $("#btn-impact").onclick = montrerImpact;
  ["#cherche-alternance", "#cherche-stages"].forEach((sel) => {
    $(sel).onchange = majNatures;
  });

  $("#btn-rome").onclick = () => {
    ajouterRome($("#rome-nouveau").value);
    $("#rome-nouveau").value = "";
  };
  $("#btn-mot").onclick = () => {
    const mot = $("#mot-nouveau").value.trim().toLowerCase();
    const poids = Number($("#poids-nouveau").value);
    if (!mot) return toast("Terme vide", true);
    if (!(poids >= 1 && poids <= 30)) return toast("Poids attendu entre 1 et 30", true);
    if (lireEtiquettes("#mots-cles").includes(mot)) return toast("Déjà présent");
    ajouterEtiquette("#mots-cles", `<span class="etiquette" data-valeur="${mot}"
        data-poids="${poids}"><span>${mot}</span><b class="n">${poids}</b>
        <button title="Retirer">×</button></span>`);
    $("#mot-nouveau").value = ""; $("#poids-nouveau").value = "";
  };
  $("#btn-ecole").onclick = () => {
    const nom = $("#ecole-nouvelle").value.trim().toLowerCase();
    if (!nom) return toast("Nom vide", true);
    if (lireEtiquettes("#blocklist").includes(nom)) return toast("Déjà présent");
    ajouterEtiquette("#blocklist", `<span class="etiquette" data-valeur="${nom}">
        <span>${nom}</span><button title="Retirer">×</button></span>`);
    $("#ecole-nouvelle").value = "";
  };
  document.querySelectorAll("[data-defaut]").forEach((b) => {
    b.onclick = () => retablirDefaut(b.dataset.defaut);
  });
  $("#btn-rescore").onclick = () => {
    $("#etat-parametres").textContent = "";
    changerVue("a_traiter");
    lancerTache("rescore");
  };

  // En mode tiroir (ecran etroit) le panneau recouvre la page : il faut
  // pouvoir le refermer au clic exterieur ou avec Echap.
  $("#contenu").addEventListener("click", (e) => {
    if (etat.choisie && !e.target.closest(".offre") && !e.target.closest(".detail")) {
      fermerDetail();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && etat.choisie) fermerDetail();
  });

  $("#btn-collecte").onclick = async () => {
    if (await enregistrerRecherche()) lancerTache("collecte");
  };
  $("#btn-reconnaissance").onclick = () => lancerTache("reconnaissance");
  $("#btn-lettres").onclick = () => {
    const inconnues = etat.vues.find((v) => v.cle === "a_traiter");
    if (!confirm("Générer les lettres ?

Chaque lettre coûte environ 65 000 "
               + "jetons. Lance d'abord l'inspection des formulaires pour ne "
               + "pas en écrire pour des offres qui n'en acceptent pas.")) return;
    lancerTache("lettres", { limite: 10 });
  };
  $("#btn-postuler").onclick = () => {
    if (confirm("Préparer les candidatures ? Les formulaires seront remplis "
              + "et capturés pour relecture. Rien ne sera envoyé.")) {
      lancerTache("candidatures", { canal: "lba", limite: 5, confirmer: false });
    }
  };

  rendreNav();
  changerVue("a_valider");
  if (ctx.tache) demarrerSondage();
}

demarrer().catch((e) => toast("Démarrage impossible : " + e.message, true));
