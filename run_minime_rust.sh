#!/bin/bash
# Run the Rust minime sensory engine

cd minime && cargo run --release -- "$@"