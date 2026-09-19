# Viseca-inspirierter Digital- und Employer-Branding-Style-Guide

> **Status:** Reverse Engineering anhand der öffentlichen Viseca-Websites, Stand 19. September 2026. Dies ist **kein** offizielles Viseca-Brand-Manual. Das Viseca-Logo, Originalfotos, Wortmarken und Partnerzeichen nur mit Freigabe bzw. aus den bereitgestellten Brand-Assets verwenden.

## Der prägnante Eindruck

**Klar. Schweizerisch. Digital. Zugänglich.**

Viseca inszeniert Fintech nicht als kalte Technologie, sondern als verlässliche, alltagsnahe Dienstleistung: viel Weissraum, ruhige Grauwerte, echte oder glaubwürdige Arbeits- und Nutzungssituationen sowie ein einziges warmes Signalorange für Entscheidungen. Die Gestaltung ist funktional statt dekorativ; die Sprache ist direkt, freundlich und auf Augenhöhe.

## Visuelles System

| Element | Beobachtete Regel | Umsetzung |
| --- | --- | --- |
| Hintergrund | Nahezu durchgehend weiss | `#FFFFFF`; Abschnitte durch Raum und Fotografie trennen, nicht durch viele Flächenfarben. |
| Primärtext | Weiches, dunkles Anthrazit | Fliesstext `#333333`, Überschriften meist `#4C4C4C`; keine harte, rein schwarze Textmasse. |
| Akzent / CTA | Warmes Viseca-Orange | Beobachtet: `#F69F29` (`rgb(246,159,41)`). Nur für den wichtigsten Button, Badges oder kleine Interaktionssignale. |
| Typografie | Roboto, sehr leicht gesetzt | `Roboto, Arial, sans-serif`; Body 16/22 px, Gewicht 300; Buttons 16/24 px, Gewicht 700. |
| H1 | Gross, ruhig, oft auf Bild | 40/50 px, Gewicht 300, weiss auf ausreichend dunkler Bildzone oder mit sehr feinem Schatten. |
| H2 | Leicht und sachlich | 32/40 px, Gewicht 300, Anthrazit. |
| Buttons | Eindeutig statt verspielt | Orange Fläche, schwarze fette Schrift, 5 px Radius, ca. `10px 20px` Innenabstand. Keine Pill-Buttons, Verläufe oder übertriebenen Schatten. |
| Header | Kompakt und weiss | Weisser Header, dünne Unterkante, links Logo, rechts klare Navigation bzw. Hamburger. Auf Desktop wirkt der Header etwa 89 px hoch. |
| Raster | Grosszügig, editorial | Breite, ruhige Bildbühnen; darunter klare, luftige Inhaltscontainer. Auf mobilen Ansichten einspaltig, mit grossen vertikalen Abständen. |

### Implementierungs-Tokens

```css
:root {
  --viseca-white: #ffffff;
  --viseca-ink: #333333;
  --viseca-heading: #4c4c4c;
  --viseca-orange: #f69f29;
  --viseca-link: #4c4c4c;
  --viseca-font: Roboto, Arial, sans-serif;
  --radius-control: 5px;
}

body {
  color: var(--viseca-ink);
  background: var(--viseca-white);
  font: 300 16px/1.375 var(--viseca-font);
}
h1 { font: 300 40px/1.25 var(--viseca-font); }
h2 { font: 300 32px/1.25 var(--viseca-font); color: var(--viseca-heading); }
.cta {
  display: inline-block;
  padding: 10px 20px;
  border-radius: var(--radius-control);
  background: var(--viseca-orange);
  color: #000;
  font: 700 16px/24px var(--viseca-font);
  text-decoration: none;
}
```

## Bildsprache und Komponenten

1. **Hero zuerst.** Nutze ein breitformatiges, glaubwürdiges Foto aus der Arbeits- oder Zahlungswelt: Architektur, Arbeitsplatz, Smartphone in Benutzung, konzentrierter Austausch. Das Bild darf leicht atmosphärisch sein, bleibt aber realistisch und nicht werblich überstilisiert.
2. **Headline direkt auf dem Bild.** Links unten oder links mittig, mit grosszügigem Rand. Bei unruhigem Foto eine zurückhaltende Abdunklung oder einen Schatten einsetzen – keinen schweren Farbblock.
3. **Weissraum statt Dekoration.** Nach dem Hero folgt eine ruhige, weisse Inhaltszone. Karten sind schlicht; Trennung entsteht über Abstand, nicht über starke Borders, Farbflächen oder Schatten.
4. **Nutzenlisten sachlich machen.** Kreishäkchen bzw. kleine orange Kontursymbole, kurze Zeilen, keine Piktogramm-Wolken.
5. **Presse als Editorial.** Datierte Meldungen als klare Liste bzw. Akkordeon nach Jahr. Datum steht als Metadatum vor dem Titel; der Titel ist der Link. Kontaktblock und Aboformular sind nüchtern, nicht kampagnenhaft.
6. **Ein CTA pro Entscheidung.** Orange nie inflationär einsetzen. Sekundäre Aktionen als dunkler Textlink mit einem kleinen Pfeil behandeln.

## Employer Branding: Botschaft und Stimme

### Kernversprechen

Die öffentliche Arbeitgeberkommunikation verbindet eine führende Schweizer Fintech- und Payment-Position mit menschlicher Zusammenarbeit:

- die Zukunft des bargeldlosen Bezahlens in der Schweiz gestalten;
- dynamisches Marktumfeld, moderne digitale Lösungen und konkrete Verantwortung;
- flache Hierarchien, unkomplizierte Zusammenarbeit, Du-Kultur und «one team»;
- Kundenfokus, Lösungsorientierung, Innovation, Motivation und Verantwortung;
- flexibles Arbeiten, moderne Arbeitswelten und Gesundheitsförderung.

### Schreibregeln

- Schreibe im **Du**, aktiv und unkompliziert: «Gestalte», «arbeite», «lerne uns kennen».
- Beginne mit einer konkreten Frage oder Einladung, nicht mit einem Superlativ.
- Verbinde Technologie mit Wirkung für Menschen: sicher, einfach, praktisch, kundenorientiert.
- Belege Benefits konkret, aber ohne Benefit-Lawine. Gruppiere nach Arbeitsalltag, Entwicklung und Gesundheit.
- Nutze kurze Absätze, klare Zwischenüberschriften und handlungsorientierte CTAs.
- Meide Buzzword-Überladung, künstliche Disruption, überzogenes «Family»-Vokabular und anonyme Stock-Ästhetik.

### Formulierungsbausteine

| Zweck | Viseca-nahe Form |
| --- | --- |
| Einstieg | «Möchtest du gemeinsam mit uns die Zukunft des bargeldlosen Bezahlens in der Schweiz gestalten?» |
| Kultur | «Wir arbeiten offen, unkompliziert und auf Augenhöhe.» |
| Verantwortung | «Du übernimmst Verantwortung und kannst Ideen einbringen.» |
| Technologie | «Wir entwickeln digitale Lösungen, die Bezahlen einfach, sicher und bequem machen.» |
| CTA | «Stellenangebote ansehen», «Mehr über unsere Benefits», «Lerne uns kennen» |

## Copy-Template: Karriere-Landingpage

Dieses Markdown liefert die passende Inhaltsdramaturgie. Für die visuelle Übereinstimmung im CMS die obenstehenden Tokens, das Hero-Layout und eigene, freigegebene Bildassets ergänzen.

```md
# Gute Gründe, bei [Unternehmen] zu arbeiten

[Button: Offene Stellen]

Als innovatives Unternehmen in einem dynamischen Markt gestalten wir Lösungen, die den Alltag einfacher machen. Bei uns arbeitest du offen, unkompliziert und gemeinsam mit Menschen, die Verantwortung übernehmen.

## Mehr als ein Job

Spannende Aufgaben sind wichtig. Ebenso wichtig ist ein Umfeld, in dem du Ideen einbringen, Neues ausprobieren und deine Entwicklung aktiv gestalten kannst. Wir arbeiten als Team – mit kurzen Wegen und Raum für Eigeninitiative.

## Was dich erwartet

### Arbeiten, wie es zum Leben passt

Flexible Arbeitszeiten, moderne Arbeitsplätze und die Möglichkeit, dort zu arbeiten, wo du wirksam bist.

### Zusammen weiterdenken

Wir hören zu, finden Lösungen und gehen den nächsten Schritt gemeinsam. Kundenfokus und Teamgeist gehören für uns zusammen.

### Gesundheit und Entwicklung

Ein gutes Arbeitsumfeld bedeutet für uns: Zeit für Erholung, Angebote für Gesundheit und Entwicklungsperspektiven, die zu dir passen.

## Gestalte mit uns die Zukunft des Bezahlens

Du möchtest Technologie mit echtem Nutzen verbinden? Dann lerne unsere Teams und offenen Stellen kennen.

[Button: Stellenangebote ansehen]
```

## No-Gos

- Kein fremdes oder nachgezeichnetes Viseca-Logo ohne Freigabe.
- Keine Verwendung der Original-Websitefotos als «neue» Kampagnenbilder ohne Lizenz.
- Kein dunkles Neongradient-/Cyberpunk-Fintech-Look; Viseca wirkt hell, ruhig und real.
- Keine bunten Akzentfarben neben Orange und keine überrundeten UI-Elemente.
- Keine rein behaupteten Kulturversprechen: Aussagen an sichtbaren Arbeitsalltag, Teams und konkrete Angebote knüpfen.

## Recherchebasis

- [Viseca Card Services – Startseite](https://www.viseca.ch/de): beobachtetes Karten-/Nutzenlayout, CTA-System und Bildsprache.
- [Viseca Payment Services – Jobs & Karriere](https://viseca-payment.ch/de/jobs/): Karrierehero, Tonalität, Bewerbungsprozess und Arbeitgeber-Navigation.
- [Arbeiten bei Viseca](https://viseca-payment.ch/de/jobs/arbeiten-bei-viseca/): Werte, Teamkultur und Innovationsnarrativ.
- [Benefits](https://viseca-payment.ch/de/jobs/benefits/): konkrete Benefits, moderne Arbeitswelten und Friendly-Work-Space-Kontext.
- [Medien](https://viseca-payment.ch/de/medien/): Bildhero, sachliches Presselayout, Meldungsarchiv und Kontaktstruktur.
