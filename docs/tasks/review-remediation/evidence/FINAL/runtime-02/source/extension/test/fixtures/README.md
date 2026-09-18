# Page fixtures

Sample pages that stand in for the shapes Untangle meets on real websites.
`test/content-parsing.test.mjs` runs the real `content.js` DOM analysis against
each one through `test/dom-harness.mjs`.

Each file is a complete, standalone HTML document, so you can also open one in a
browser and try the unpacked extension against it by hand.

| Fixture                           | Page shape it stands for                                                                                                      |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `wordpress-entry-content.html`    | WordPress/blog post: `<article>` wrapping `.entry-content`, with post meta, share widgets, related posts and a comment thread |
| `news-article-noise.html`         | News site: site header, nav, sidebar `<aside>`, footer around a bare `<article>`                                              |
| `daily-dev-markdown.html`         | daily.dev-style app shell whose body is a hashed `markdown_markdown__…` container                                             |
| `role-main-article-body.html`     | App shell using `[role="main"]` plus `.article-body` instead of `<article>`                                                   |
| `main-tag-plain.html`             | Documentation page: plain `<main>`, no article wrapper or content class                                                       |
| `div-soup.html`                   | Legacy page with no `<article>`, no `<main>`, no landmark roles at all                                                        |
| `nested-wrappers.html`            | Content buried under several nested layout `<div>`s                                                                           |
| `list-and-quote.html`             | Prose carried by headings, `<li>` and `<blockquote>` rather than `<p>`                                                        |
| `multiple-articles.html`          | Index/feed page with several `<article>` cards plus one real post                                                             |
| `itemprop-article-body.html`      | schema.org markup: `[itemprop="articleBody"]`                                                                                 |
| `inline-markup.html`              | Sentences broken up by `<a>`, `<em>`, `<strong>`, `<code>`                                                                    |
| `repeated-sentences.html`         | The same sentence appearing in more than one block                                                                            |
| `hidden-content.html`             | Collapsed/`hidden`/`display:none` regions next to visible prose                                                               |
| `typographic-text.html`           | Non-breaking spaces, curly quotes, en/em dashes, zero-width characters                                                        |
| `article-in-excluded-region.html` | An `<article>` that only exists inside `nav`/`footer` chrome                                                                  |
| `article-inside-main.html`        | Both landmarks present: an `<article>` nested inside `<main>`                                                                 |
| `table-layout.html`               | Legacy table-based layout with no landmarks and no recognisable chrome classes                                                |
| `cjk-article.html`                | Japanese article: `lang="ja"` and prose with no inter-word spaces                                                             |

## Adding a fixture

1. Drop a complete HTML document in this directory.
2. Add a row to the table above saying which real-world shape it represents.
3. Add its expectations to `test/content-parsing.test.mjs`.

Give the blocks you assert on stable `id` attributes — the tests compare ids, so
they stay readable and do not depend on document order.
