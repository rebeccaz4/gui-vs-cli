# Tasks to rerun after "update v2"

If you have results produced with the v2 task set (commit 4d9e24d), rerun the tasks listed here. All other tasks in the 340-task set are byte-identical to v2 (task.json, input files) and use verifier code that did not change, so their v2 results stay valid.

**88 of 340 tasks** need a rerun. Plain list: `task_generator/rerun_vs_v2.txt`.

A task is listed if any of these differs from v2:
- `instruction`: the `task` text in task.json
- `checks`: the `verification` entries in task.json (commands, expected values, eval expressions)
- `input files`: files under the task's `env/` folder or the `env` field of task.json
- `verifier code`: the task uses a verifier command (`verifiers/<app>/<app>.py`) whose code changed in this update. This is not visible in task.json, so it is listed explicitly with the affected commands.

Tasks removed from v2 (116) are simply gone; do not report results for them. The task list and file hashes are in `task_generator/manifest_v2_update.json`.

| # | Task | App | Category | What changed vs v2 | Verifier commands affected |
|---:|---|---|---|---|---|
| 1 | calc_cg_630a8bde | libreoffice_calc | Spreadsheets | instruction |  |
| 2 | calc_cg_69760751 | libreoffice_calc | Spreadsheets | instruction |  |
| 3 | calc_cg_6d922d9a | libreoffice_calc | Spreadsheets | instruction |  |
| 4 | calc_cg_7cc28048 | libreoffice_calc | Spreadsheets | instruction, checks |  |
| 5 | calc_cg_826a90a9 | libreoffice_calc | Spreadsheets | checks |  |
| 6 | calc_cg_aaaf7c52 | libreoffice_calc | Spreadsheets | instruction, checks |  |
| 7 | calc_cg_b99ac46d | libreoffice_calc | Spreadsheets | instruction, checks |  |
| 8 | calc_cg_cf78eed7 | libreoffice_calc | Spreadsheets | instruction |  |
| 9 | calc_cg_d421e418 | libreoffice_calc | Spreadsheets | instruction |  |
| 10 | calc_export_contacts_multi_format | libreoffice_calc | Spreadsheets | verifier code | `check-file-format` |
| 11 | calc_osw_7e287123 | libreoffice_calc | Spreadsheets | instruction |  |
| 12 | calc_osw_881deb30 | libreoffice_calc | Spreadsheets | instruction |  |
| 13 | calc_pref_default_sheets_and_save_format | libreoffice_calc | Spreadsheets | verifier code | `check-calc-pref` |
| 14 | calc_pref_sheet_count_3_odf_format | libreoffice_calc | Spreadsheets | verifier code | `check-calc-pref` |
| 15 | calc_pref_sheet_count_4_xlsx_cm | libreoffice_calc | Spreadsheets | verifier code | `check-calc-pref` |
| 16 | calc_pref_sheet_count_6_odf_100th_mm | libreoffice_calc | Spreadsheets | verifier code | `check-calc-pref` |
| 17 | calc_pref_sheet_count_7_excel2003 | libreoffice_calc | Spreadsheets | verifier code | `check-calc-pref` |
| 18 | chrome_dom_inspection_wikipedia | chrome | Web | verifier code | `check-element-exists` |
| 19 | chrome_download_attention_paper | chrome | Web | verifier code | `check-file-contains` |
| 20 | chrome_download_resnet_paper | chrome | Web | verifier code | `check-file-contains` |
| 21 | chrome_form_fill_httpbin | chrome | Web | verifier code | `check-page-contains` |
| 22 | chrome_form_fill_httpbin2 | chrome | Web | verifier code | `check-file-contains` |
| 23 | chrome_form_fill_httpbin3 | chrome | Web | verifier code | `check-file-contains` |
| 24 | freecad_change_unit_schema | freecad | CAD & 3D | verifier code | `check-preference` |
| 25 | freecad_gap_draft_wire_polygon | freecad | CAD & 3D | instruction, verifier code | `check-object-exists`, `check-parameter-value` |
| 26 | freecad_gap_partdesign_revolve_bottle | freecad | CAD & 3D | instruction, verifier code | `check-object-exists`, `check-object-type`, `check-parameter-value` |
| 27 | freecad_gap_spreadsheet_parametric | freecad | CAD & 3D | verifier code | `check-object-exists`, `check-object-type`, `check-parameter-value` |
| 28 | freecad_preferences_multi_tune | freecad | CAD & 3D | instruction, checks, verifier code | `check-preference` |
| 29 | freecad_set_theme_preference | freecad | CAD & 3D | instruction, checks, verifier code | `check-preference` |
| 30 | gimp_gap_layer_mask_gradient_reveal | gimp | Visual Design | instruction, checks |  |
| 31 | krita_add_document_metadata | krita | Visual Design | instruction |  |
| 32 | krita_export_multiple_formats | krita | Visual Design | input files, instruction, checks |  |
| 33 | krita_transform_mask_rotation | krita | Visual Design | instruction, verifier code | `check-layer-exists`, `check-layer-node-type`, `check-mask-of` |
| 34 | obs_add_sources_to_existing | obs | Video & Streaming | instruction |  |
| 35 | obs_consolidate_into_single_scene | obs | Video & Streaming | instruction |  |
| 36 | obs_event_multicam_six_scenes | obs | Video & Streaming | instruction |  |
| 37 | obs_five_scene_broadcast | obs | Video & Streaming | instruction |  |
| 38 | obs_gaming_stream_layout | obs | Video & Streaming | instruction |  |
| 39 | obs_gap_chroma_key_filter | obs | Video & Streaming | instruction, checks |  |
| 40 | obs_hide_but_keep_sources | obs | Video & Streaming | instruction |  |
| 41 | obs_multi_collection_profiles | obs | Video & Streaming | instruction |  |
| 42 | obs_multi_source_scene | obs | Video & Streaming | instruction |  |
| 43 | obs_news_broadcast_layout | obs | Video & Streaming | instruction |  |
| 44 | obs_podcast_two_person | obs | Video & Streaming | instruction |  |
| 45 | obs_relocate_sources_across_scenes | obs | Video & Streaming | instruction |  |
| 46 | obs_rename_and_reorganize_scenes | obs | Video & Streaming | instruction |  |
| 47 | obs_scene_split_refactor | obs | Video & Streaming | instruction |  |
| 48 | obsidian_add_links_to_existing | obsidian | Knowledge | input files |  |
| 49 | obsidian_appearance_setup | obsidian | Knowledge | input files, instruction, checks |  |
| 50 | obsidian_bookmarks_curation | obsidian | Knowledge | instruction |  |
| 51 | obsidian_bug_tracker | obsidian | Knowledge | input files |  |
| 52 | obsidian_configure_editor | obsidian | Knowledge | input files, instruction |  |
| 53 | obsidian_custom_hotkeys | obsidian | Knowledge | input files, instruction, checks |  |
| 54 | obsidian_digital_garden | obsidian | Knowledge | input files, instruction, checks |  |
| 55 | obsidian_enable_core_plugins | obsidian | Knowledge | input files, instruction, checks |  |
| 56 | obsidian_full_dev_setup | obsidian | Knowledge | input files, instruction, checks |  |
| 57 | obsidian_interview_prep | obsidian | Knowledge | input files, checks |  |
| 58 | obsidian_language_vocab | obsidian | Knowledge | input files |  |
| 59 | obsidian_music_collection | obsidian | Knowledge | input files, checks |  |
| 60 | obsidian_personal_crm | obsidian | Knowledge | input files |  |
| 61 | obsidian_recipe_vault | obsidian | Knowledge | input files |  |
| 62 | obsidian_reorganize_tags | obsidian | Knowledge | input files |  |
| 63 | obsidian_toggle_core_features | obsidian | Knowledge | input files, instruction, checks |  |
| 64 | obsidian_workout_log | obsidian | Knowledge | input files |  |
| 65 | shotcut_default_profile_atsc | shotcut | Video & Streaming | instruction, checks |  |
| 66 | shotcut_set_theme_dark | shotcut | Video & Streaming | instruction |  |
| 67 | shotcut_v2_default_profile_dv_pal | shotcut | Video & Streaming | instruction, checks |  |
| 68 | shotcut_v2_default_profile_uhd_2160p_30 | shotcut | Video & Streaming | instruction, checks |  |
| 69 | shotcut_v2_uhd_4k_project | shotcut | Video & Streaming | instruction |  |
| 70 | writer_cg_10c36365 | libreoffice_writer | Documents | checks |  |
| 71 | writer_cg_63e1cce9 | libreoffice_writer | Documents | checks |  |
| 72 | writer_cg_68b15b4e | libreoffice_writer | Documents | instruction, checks |  |
| 73 | writer_cg_b461cf34 | libreoffice_writer | Documents | instruction |  |
| 74 | writer_cg_cce430f6 | libreoffice_writer | Documents | instruction |  |
| 75 | writer_cg_d853218b | libreoffice_writer | Documents | checks |  |
| 76 | writer_cg_e37f90ef | libreoffice_writer | Documents | instruction |  |
| 77 | writer_cg_ee7010dd | libreoffice_writer | Documents | input files, instruction, checks |  |
| 78 | writer_cg_f360764c | libreoffice_writer | Documents | instruction, checks |  |
| 79 | writer_osw_88fe4b2d | libreoffice_writer | Documents | checks |  |
| 80 | zotero_add_author_to_survey | zotero | Knowledge | instruction |  |
| 81 | zotero_add_note_to_item | zotero | Knowledge | input files, instruction |  |
| 82 | zotero_bulk_tag_multiple_items | zotero | Knowledge | instruction |  |
| 83 | zotero_edit_multiple_fields_bert | zotero | Knowledge | instruction |  |
| 84 | zotero_export_collection_bibtex | zotero | Knowledge | verifier code | `check-bibtex-count`, `check-bibtex-title` |
| 85 | zotero_export_two_collection_bibtex_with_publisher | zotero | Knowledge | verifier code | `check-bibtex-count`, `check-bibtex-title` |
| 86 | zotero_gap_advanced_search_export_results | zotero | Knowledge | instruction, verifier code | `check-bibtex-count`, `check-bibtex-title` |
| 87 | zotero_subcollection_neural | zotero | Knowledge | input files |  |
| 88 | zotero_tag_bert_important | zotero | Knowledge | instruction |  |

Counts (a task can have several): instruction 57, checks 27, verifier code 22, input files 20
