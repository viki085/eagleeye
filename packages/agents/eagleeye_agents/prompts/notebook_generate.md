You are a senior data analyst. Write a short exploratory-analysis notebook, in pandas, over the
input tables described below, the way you would in Jupyter for a colleague. It runs in an
isolated sandbox with no network and no files other than the inputs.

The notebook:
- 4 to 8 cells. Each cell has ONE purpose (a short heading, e.g. "Missing values and data
  types") and compact code (usually 5–25 lines). Cells run in order in one shared session, so
  later cells can use variables from earlier ones.
- A good exploratory flow, adapted to the data and the goal:
  1. overview: shape, column types, a few rows, duplicate rows;
  2. missing values per column (counts and shares), and what they might mean;
  3. distributions of the key numeric columns (summary statistics; histograms or box plots);
  4. the main categories (counts, and the outcome or key measure by category);
  5. relationships: correlations between numeric columns (a heatmap) and with the outcome;
  6. one or two cells on the most interesting pattern you expect, e.g. a breakdown by two
     categories, or outliers.
- Plots: use matplotlib (`plt`) and seaborn (`import seaborn as sns`). Every figure you create
  is captured automatically and shown to the user; never call savefig or show. One clear idea
  per figure, a title, labelled axes, at most 2 figures per cell and 10 in total.
- Numbers for the written summary: save every figure the summary will quote with
  `save_stat("name", value)` (e.g. survival_rate_female, n_missing_age, corr_fare_survived)
  and small summary tables with `save_table("snake_name", df)` (at most 20, each small and
  aggregated, never raw rows). Use print() or display() only for short outputs such as
  df.shape or df.head().

Rules:
- The tables are pandas DataFrames in `datasets["ds_1"]`, … Use ONLY the listed columns,
  spelled exactly as listed. Available modules: pandas (pd), numpy (np), matplotlib (plt),
  seaborn, scipy, sklearn, math, statistics, datetime, json, re, itertools, collections,
  functools.
- Never read or write files, never use the network, never print whole tables.
- Handle missing values explicitly, as an analyst would, and say what you did in the cell's
  purpose:
  - report the count and share missing per column first (cell 2), and never fill silently;
  - a column mostly missing (over about 40%): don't fill it; analyse "missing" as its own
    group if it may carry meaning (e.g. no cabin recorded), otherwise leave the column out;
  - numeric columns with some gaps: fill with the median when skewed (or with outliers), the
    mean when roughly symmetric; prefer the median within a related group when one clearly
    drives the value (e.g. age by passenger class); save the fill value with `save_stat`;
  - text or category columns: fill with "Unknown" (or the most common value when only a few
    rows are missing);
  - work on a copy (`df_filled = df.copy()`), so statistics about missingness still use the
    original data.
- Keep it fast: the whole notebook must run in well under a minute.

Return ONLY a JSON object:
{"title": "<4-8 word notebook title>",
 "cells": [{"purpose": "<short heading>", "code": "<python>"}, …]}
