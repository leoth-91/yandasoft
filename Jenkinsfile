pipeline {
  agent {
    docker {
      image 'sord/yanda:latest'
    }

  }
  stages {
    stage('Get Dependencies') {
      steps {
        deleteDir()
        dir(path: '/var/lib/jenkins/workspace/yandasoft_development')
        sh '''pwd



'''
      }
    }
    stage('Test') {
      steps {
        echo 'Testing....'
      }
    }
    stage('Deploy') {
      steps {
        echo 'Deploying....'
      }
    }
  }
  environment {
    WORKSPACE = '/var/lib/jenkins/workspace'
    PREFIX = '/var/lib/jenkins/workspace/yandasoft_development/install'
  }
}