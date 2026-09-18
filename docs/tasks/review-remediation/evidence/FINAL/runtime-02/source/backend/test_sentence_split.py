import unittest

from core.pipeline import (
    _clean_article_content,
    _coarse_split_sentences,
    _extract_article_text,
    _finalize_sentence_split,
    _reconcile_dropped_units,
    _sentence_in_content,
)


class SentenceSplitTests(unittest.TestCase):
    def test_splits_after_closing_quote_before_next_sentence(self):
        content = (
            "The proposed changes would include a provision that says, “Artificial intelligence shall serve "
            "the freedom of the individual and the prosperity of society, ensuring that risks are mitigated "
            "and that the advantages it provides are fully realized.” Dozens of other changes would include "
            "expanding postal voting, increasing mandatory schooling from nine to 11 years, and banning "
            "retroactive taxation."
        )

        sentences = _coarse_split_sentences(content)

        self.assertGreaterEqual(len(sentences), 2)
        self.assertTrue(
            sentences[0].startswith("The proposed changes would include a provision that says,")
        )
        self.assertTrue(
            any("Artificial intelligence shall serve" in sentence for sentence in sentences)
        )
        self.assertTrue(
            any(sentence.startswith("Dozens of other changes") for sentence in sentences)
        )
        self.assertTrue(all(len(sentence) <= 220 for sentence in sentences))

    def test_preserves_paragraph_breaks_from_html(self):
        content = "First sentence in paragraph one.\n\nSecond paragraph starts here."

        cleaned = _clean_article_content(content)
        self.assertIn("\n\n", cleaned)

        sentences = _coarse_split_sentences(content)
        self.assertEqual(len(sentences), 2)
        self.assertEqual(sentences[0], "First sentence in paragraph one.")
        self.assertEqual(sentences[1], "Second paragraph starts here.")

    def test_splits_single_newline_after_sentence_end(self):
        content = "First sentence ends here.\nSecond sentence starts here."

        sentences = _coarse_split_sentences(content)

        self.assertEqual(len(sentences), 2)
        self.assertEqual(sentences[0], "First sentence ends here.")
        self.assertEqual(sentences[1], "Second sentence starts here.")

    def test_splits_short_discussion_prompts(self):
        content = (
            "Discussion A - Greece wants to add a constitutional rule saying AI must serve human "
            "freedom and social well-being. Do you think governments should have the power to limit "
            "how AI is used? Why or why not? Would you want your government to add a similar rule "
            "in your country? Why do you say so? Discuss."
        )

        sentences = _coarse_split_sentences(content)

        self.assertEqual(len(sentences), 6)
        self.assertEqual(
            sentences[0],
            "Discussion A - Greece wants to add a constitutional rule saying AI must serve human freedom and social well-being.",
        )
        self.assertEqual(
            sentences[1],
            "Do you think governments should have the power to limit how AI is used?",
        )
        self.assertEqual(sentences[2], "Why or why not?")
        self.assertEqual(
            sentences[3],
            "Would you want your government to add a similar rule in your country?",
        )
        self.assertEqual(sentences[4], "Why do you say so?")
        self.assertEqual(sentences[5], "Discuss.")

    def test_prefers_shorter_units_for_long_colon_and_conjunction_clauses(self):
        content = (
            "“These challenges already dominate today: from the climate crisis and protection of water "
            "resources to renewable energy sources, but above all, the use of artificial intelligence,” "
            "the prime minister said."
        )

        sentences = _coarse_split_sentences(content)

        self.assertGreaterEqual(len(sentences), 3)
        self.assertTrue(sentences[0].startswith("“These challenges already dominate today:"))
        self.assertTrue(any("climate crisis" in sentence for sentence in sentences))
        self.assertTrue(any("above all" in sentence for sentence in sentences))
        self.assertTrue(sentences[-1].endswith("the prime minister said."))
        self.assertTrue(all(len(sentence) <= 220 for sentence in sentences))

    def test_finalize_sentence_split_keeps_verbatim_substrings_only(self):
        content = (
            "This post is part of The Software Architecture Chronicles, a series of posts about Software Architecture. "
            "In them, I write about what I've learned."
        )
        finalized = _finalize_sentence_split(
            [
                "This post is part of The Software Architecture Chronicles, a series of posts about Software Architecture.",
                "Paraphrased sentence that is not in the article.",
            ],
            content,
        )

        self.assertEqual(len(finalized), 1)
        self.assertTrue(_sentence_in_content(finalized[0], content))

    def test_coarse_split_allows_more_than_eighty_sentences_by_default(self):
        content = " ".join(
            f"Sentence number {index} has enough words for analysis." for index in range(1, 101)
        )

        sentences = _coarse_split_sentences(content)

        self.assertEqual(len(sentences), 100)

    def test_finalize_sentence_split_keeps_short_meaningful_units_and_rejects_code(self):
        content = (
            "Advantages of database replication:\n\n"
            "Better performance\n\n"
            "Higher availability\n\n"
            "GET /users/12 - Retrieve user object for id = 12\n\n"
            '{"id": 12, "firstName": "John"}'
        )

        finalized = _finalize_sentence_split(
            [
                "Advantages of database replication:",
                "Better performance",
                "Higher availability",
                "GET /users/12 - Retrieve user object for id = 12",
                '{"id": 12, "firstName": "John"}',
            ],
            content,
        )

        self.assertEqual(
            finalized,
            [
                "Advantages of database replication:",
                "Better performance",
                "Higher availability",
            ],
        )

    def test_extract_article_text_preserves_study_blocks_and_skips_code(self):
        html = """
        <html>
          <body>
            <nav>Home Pricing Docs</nav>
            <article>
              <p>An example of the API response in JSON format is shown below:</p>
              <p><em>GET /users/12 - Retrieve user object for id = 12</em></p>
              <pre><code>{
                "id": 12,
                "firstName": "John",
                "lastName": "Smith"
              }</code></pre>
              <h2>Database</h2>
              <p>With the growth of the user base, one server is not enough.</p>
              <p>Advantages of database replication:</p>
              <ul>
                <li>Better performance</li>
                <li>Higher availability</li>
              </ul>
            </article>
          </body>
        </html>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/system-design",
            page_title="System Design",
        )

        self.assertNotIn("GET /users/12", content)
        self.assertNotIn('"firstName"', content)
        self.assertIn("An example of the API response in JSON format is shown below:", content)
        self.assertIn("\n\nDatabase\n\n", content)
        self.assertIn("\n\nAdvantages of database replication:\n\n", content)
        self.assertIn("\n\nBetter performance\n\n", content)
        self.assertIn("\n\nHigher availability", content)

    def test_extract_article_text_skips_inline_code_without_dropping_sentence_tail(self):
        html = """
        <article>
          <p>The API endpoint <code>api.mysite.com</code> forwards requests to the web server.</p>
          <p>This sentence keeps the extracted article long enough for validation and describes the architecture in normal prose.</p>
        </article>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/inline-code",
            page_title="Inline Code",
        )

        self.assertIn(
            "The API endpoint forwards requests to the web server.",
            content,
        )
        self.assertNotIn("api.mysite.com", content)

    def test_extract_article_text_falls_back_to_leaf_div_blocks(self):
        html = """
        <html>
          <body>
            <nav><div>Pricing Docs Login</div></nav>
            <main>
              <div>
                <span>First div-only paragraph explains the architecture and should be included as study text.</span>
              </div>
              <div>
                <span>Second div-only paragraph keeps the extracted article long enough and should remain separate.</span>
              </div>
              <div><code>{"id": 12, "firstName": "John"}</code></div>
            </main>
          </body>
        </html>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/div-only",
            page_title="Div Only",
        )

        self.assertIn("First div-only paragraph explains the architecture", content)
        self.assertIn("\n\nSecond div-only paragraph keeps", content)
        self.assertNotIn("Pricing Docs Login", content)
        self.assertNotIn('"firstName"', content)

    def test_extract_article_text_keeps_unknown_non_noise_blocks(self):
        html = """
        <html>
          <body>
            <main>
              <section>
                <span>First custom block explains how requests move through the system and should be kept.</span>
              </section>
              <section>
                <span>Second custom block is valid prose even though it does not use paragraph tags.</span>
              </section>
            </main>
            <footer>
              <section>Footer links should not be included in extracted study text.</section>
            </footer>
          </body>
        </html>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/custom-blocks",
            page_title="Custom Blocks",
        )

        self.assertIn("First custom block explains how requests move through the system", content)
        self.assertIn("Second custom block is valid prose", content)
        self.assertNotIn("Footer links", content)

    def test_extract_article_text_adds_residual_blocks_after_clear_blocks(self):
        html = """
        <html>
          <body>
            <main>
              <article>
                <p>This clear paragraph is long enough to pass extraction on its own and should stay as a fixed source block for the AI splitter.</p>
                <section>
                  <span>This custom residual section is also article prose and should be included for AI judgment.</span>
                </section>
              </article>
            </main>
          </body>
        </html>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/mixed-blocks",
            page_title="Mixed Blocks",
        )

        self.assertIn("This clear paragraph is long enough", content)
        self.assertIn("This custom residual section is also article prose", content)
        self.assertIn("AI splitter.\n\nThis custom residual section", content)

    def test_extract_article_text_keeps_prose_with_reference_numbers(self):
        html = """
        <article>
          <ul>
            <li>
              <p>If the master database goes offline, a slave database will be promoted to be the new master.
              All the database operations will be temporarily executed on the new master database.
              Interested readers should refer to the listed reference materials [4] [5].</p>
            </li>
          </ul>
          <p>Figure 6 shows the system design after adding the load balancer and database replication.</p>
        </article>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/database-replication",
            page_title="Database Replication",
        )

        self.assertIn("If the master database goes offline", content)
        self.assertIn("reference materials [4] [5]", content)

    def test_extract_article_text_skips_sidebar_built_as_div_with_role(self):
        # Regression test: a sidebar implemented as <div role="complementary">
        # (rather than a literal <aside> tag) used to be scraped as article
        # prose and appended right after the real content, because
        # SKIPPED_HTML_TAGS only matched tag names.
        html = """
        <html>
          <body>
            <article>
              <p>This article has more than one real paragraph so the extracted text passes the minimum length check.</p>
              <p>This is the last real sentence of the article and should remain the tail of the extracted text.</p>
            </article>
            <div id="sidebar1" class="sidebar" role="complementary">
              <div class="widget widget_search">
                <h4>Search</h4>
              </div>
              <div id="archives-2" class="widget widget_archive">
                <h4>Archives</h4>
                <ul>
                  <li>August 2026</li>
                  <li>July 2026</li>
                </ul>
              </div>
            </div>
          </body>
        </html>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/sidebar",
            page_title="Sidebar",
        )

        self.assertIn("This is the last real sentence of the article", content)
        self.assertTrue(content.strip().endswith("extracted text."))
        self.assertNotIn("Search", content)
        self.assertNotIn("Archives", content)
        self.assertNotIn("August 2026", content)

    def test_extract_article_text_skips_hidden_widgets(self):
        # Regression test: third-party toolbar markup (e.g. a translation
        # widget) is often left in the DOM but hidden via inline styles or
        # the `hidden` attribute. It must not be scraped as article prose.
        html = """
        <html>
          <body>
            <article>
              <p>This article has more than one real paragraph so the extracted text passes the minimum length check.</p>
              <p>This is the only real sentence that should be extracted from the end of this page.</p>
            </article>
            <div id="WidgetFloaterPanels" style="display: none; text-align: left;">
              <span>TRANSLATE with</span>
              <div class="LanguageMenuPanel">English French German Japanese</div>
            </div>
            <div hidden>
              <p>This paragraph is hidden and must not be extracted either.</p>
            </div>
          </body>
        </html>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/hidden-widget",
            page_title="Hidden Widget",
        )

        self.assertIn("This is the only real sentence that should be extracted", content)
        self.assertNotIn("TRANSLATE with", content)
        self.assertNotIn("LanguageMenuPanel", content)
        self.assertNotIn("English French German Japanese", content)
        self.assertNotIn("This paragraph is hidden", content)

    def test_extract_article_text_recovers_after_nested_excluded_div(self):
        # Regression test: excluding a <div> by attribute (role/class/style)
        # must not desync skip-tracking for the rest of the document. Two
        # failure modes previously made this silently drop everything after
        # the excluded div:
        # 1. A same-named <div> nested inside the excluded one could pop the
        #    skip stack early by tag-name coincidence (leaking its content),
        #    or under a naive "track every nested tag" fix, an unrelated
        #    void element (like a hidden <img>) pushed onto the stack would
        #    never be popped, permanently stuck in skip mode.
        # 2. A void element (e.g. <img style="display:none">) matching the
        #    exclusion rule directly must not be pushed onto the skip stack
        #    either, since it never receives a matching end tag.
        html = """
        <html>
          <body>
            <img class="illo" style="display: none;" alt="hidden icon">
            <div class="sidebar" role="complementary">
              <div class="widget">
                <p>Nested sidebar paragraph that must not leak into the article text.</p>
              </div>
            </div>
            <article>
              <p>This is the real article paragraph that must still be extracted normally.</p>
              <p>This second real paragraph confirms parsing fully recovered after the excluded div.</p>
            </article>
          </body>
        </html>
        """

        content = _extract_article_text(
            html=html,
            page_url="https://example.com/nested-excluded-div",
            page_title="Nested Excluded Div",
        )

        self.assertIn("This is the real article paragraph", content)
        self.assertIn("This second real paragraph confirms parsing fully recovered", content)
        self.assertNotIn("Nested sidebar paragraph", content)


if __name__ == "__main__":
    unittest.main()


class ReconcileDroppedUnitsTests(unittest.TestCase):
    """The AI splitter sometimes drops legitimate body text as boilerplate;
    reconciliation restores non-boilerplate coarse units it omitted."""

    def test_restores_a_dropped_colon_lead_in_at_its_position(self):
        coarse = [
            "As part of the event, we also had 4 talks.",
            "You can also watch the full recording of my talk here:",
            "Talk: AI-Native Engineering Leadership",
        ]
        ai = [coarse[0], coarse[2]]
        result = _reconcile_dropped_units(ai, coarse)
        self.assertEqual(result, coarse)

    def test_does_not_restore_a_bare_url(self):
        coarse = [
            "Watch the recording here:",
            "https://newsletter.example.com/p/some-article-slug",
            "The talk covered AI-native workflows.",
        ]
        ai = [coarse[0], coarse[2]]
        result = _reconcile_dropped_units(ai, coarse)
        self.assertNotIn(coarse[1], result)
        self.assertEqual(result, [coarse[0], coarse[2]])

    def test_does_not_restore_boilerplate(self):
        coarse = ["Real body sentence goes here.", "Subscribe"]
        ai = [coarse[0]]
        self.assertEqual(_reconcile_dropped_units(ai, coarse), [coarse[0]])

    def test_merged_units_are_not_duplicated(self):
        # The AI merged two coarse fragments into one unit.
        result = _reconcile_dropped_units(
            ["The cat sat. The dog ran."], ["The cat sat.", "The dog ran."]
        )
        self.assertEqual(result, ["The cat sat. The dog ran."])

    def test_split_units_are_not_reinserted(self):
        # The AI split one coarse unit into two.
        result = _reconcile_dropped_units(
            ["A long clause,", "with a tail."], ["A long clause, with a tail."]
        )
        self.assertEqual(result, ["A long clause,", "with a tail."])

    def test_empty_ai_result_is_left_untouched(self):
        self.assertEqual(_reconcile_dropped_units([], ["Anything at all here."]), [])
