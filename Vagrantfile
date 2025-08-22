Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/jammy64"
  config.vm.provider "virtualbox" do |vb|
    vb.memory = 2048
  end
  # Forward pydbg port so the host can attach with VS Code
  config.vm.network "forwarded_port", guest: 5678, host: 5678
  config.vm.provision "shell", inline: <<-SHELL
    set -e
    apt-get update
    apt-get install -y python3 python3-venv python3-pip git tk
    cd /vagrant
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt
  SHELL
  config.vm.post_up_message = <<-MSG
Run 'vagrant ssh -c "./scripts/run_dev.sh"' to start CoolBox in dev mode.
  MSG
end
