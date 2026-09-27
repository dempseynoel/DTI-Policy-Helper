"""Values that are the same in every environment, so they live in code rather than config."""

# text-embedding-3-large returns 3072 dimensions. The Search index's vector field is created
# with this size (Lesson 04) and can never change without a new index.
EMBED_DIMENSIONS = 3072
