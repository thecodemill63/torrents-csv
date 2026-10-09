# shell.nix — provides a Python with Django for the search UI.
# Usage:
#   nix-shell ~/torrents-csv/ui/shell.nix --run 'bash start.sh'
# Or just let start.sh invoke it.
{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  buildInputs = [
    (pkgs.python3.withPackages (p: [ p.django ]))
  ];
  shellHook = ''
    echo "[shell.nix] django environment ready"
  '';
}
