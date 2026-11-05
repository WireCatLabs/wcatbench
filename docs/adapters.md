# Writing an adapter

An adapter is a class that matches one of the protocols in
[`src/wcatbench/core/protocols.py`](../src/wcatbench/core/protocols.py), registered under an entry point. Nothing
else in wcatbench needs to change.

```toml
# pyproject.toml of your package
[project.entry-points."wcatbench.stores"]
mystore = "my_package.store:MyStore"
```

`wcatbench adapters list` shows it once the package is installed next to wcatbench.

## A store

Look at [`stores/fts.py`](../src/wcatbench/stores/fts.py), the smallest real one.

- `open(space, workdir)` picks the namespace: a tag, a user id or a folder. One build is one space.
- `ingest(batch)` sends up to 100 records and returns what was sent and what the service refused. Record ids go in
  metadata, never in the text, so a search hit maps back to the corpus.
- `held()` asks the service what it holds, by record id. Resume sends only records that are absent or failed. A
  record still queued is not missing, so a service that charges per add is never paid twice.
- `settled(held)` says when the store is ready to answer. That can be later than indexed: a service may build its
  memories after a document is stored.
- `search(query, k)` returns hits with record ids, best first.
- Raise `TransientError` for a timeout, HTTP 429 or 5xx, and `PermanentError` for everything that will fail again.
  Only transient errors are retried.
- Set `hosted = True` if records leave the machine. A hosted store refuses a dataset marked private.

## An agent

- `ask(question)` runs the agent once and returns the answer, the cited record ids, usage, seconds and an outcome.
- The agent runs in a [`Sandbox`](../src/wcatbench/core/sandbox.py): a throwaway home folder, the system keyring
  out of reach, a fixed working folder. Do not build your own environment.
- Usage says where it came from: the agent's own usage files, a proxy on the model API, or none.
- An outcome is `completed`, `error`, `timeout` or `invalid`. A harness failure is never a wrong answer.

## A dataset

Look at [`datasets/synthetic`](../src/wcatbench/datasets/synthetic/__init__.py).

- `build(out, params)` writes four files into `out` and returns their manifest. The files are described in
  [`core/dataset_files.py`](../src/wcatbench/core/dataset_files.py): the corpus, the questions, the answer key
  and the manifest.
- The same params must give the same files on any machine. The manifest holds the corpus and key digests, and a
  run refuses a corpus that no longer matches them.
- Questions and the key are separate files. Nothing an agent can read may hold the answers.
- Mark the privacy: `synthetic`, `public` or `private`. Hosted stores refuse a private dataset.

## Tests every adapter passes

New adapters must pass the same contract tests as the built-in ones. The contract suite arrives with the first
hosted store.
