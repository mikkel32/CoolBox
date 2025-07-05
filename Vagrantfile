Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/jammy64"
  config.vm.provider "virtualbox" do |vb|
    vb.memory = 2048
  end
  # Forward debugpy port so the host can attach with VS Code
  host_port = ENV.fetch("DEBUG_PORT", "5678").to_i
  config.vm.network "forwarded_port", guest: 5678, host: host_port
  config.vm.provision "shell", inline: <<-SHELL
    set -e
    apt-get update
    apt-get install -y python3 python3-venv python3-pip git tk
    cd /vagrant
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt debugpy
  SHELL
  config.vm.post_up_message = <<-MSG
Run 'vagrant ssh -c "./scripts/run_debug.sh"' to start CoolBox in debug mode.
  MSG
end
