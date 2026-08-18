# Retrieval Basics

This release demo fixture explains the main retrieval mechanisms in plain language.

## Dense Retrieval

Dense retrieval turns a question and each document chunk into vectors. Similar
meaning produces a high similarity score, even when the words are not identical.
It is useful for semantic matches and paraphrases.

## BM25

BM25 is a sparse lexical retrieval method. It scores query terms by term
frequency, inverse document frequency, and document length normalization. It is
strong when the important words, identifiers, or names appear literally.

## Hybrid Retrieval

Hybrid retrieval combines dense and BM25 candidate lists. The two channels cover
different failure modes: dense search finds related meaning, while BM25 protects
exact terminology and rare tokens.

## Reciprocal Rank Fusion (RRF)

RRF combines ranked lists by adding a reciprocal rank contribution from each
channel. A typical contribution is 1 / (k + rank), where k is a stabilizing
constant. RRF gives a document that ranks well in both channels a strong fused
rank without requiring the raw scores to have the same scale. This is why RRF is
useful in Hybrid Retrieval.

## Reranker

A reranker receives the fused candidate set and scores the question and chunk
together with a more expensive model. It can improve the final ordering after
the inexpensive first-stage retrieval.
