#!/usr/bin/env python3
#
# This script automates 3 things:
# 1) Create Dockerfiles for all MPI implementations.
# 2) If required, create the corresponding Docker images.
# 3) Create sample SLURM batch files.
# 
# Author: Paulus Lahur
#
#------------------------------------------------------------------------------
# SETTINGS
#
# Docker images will be created for all:
# - Specific machine targets
# - All MPI targets in generic machine target
#
# Note that, for specific machine, MPI target is already specified.
# Example:
# machine_targets = ["generic", "galaxy"]
machine_targets = ["galaxy"]

# MPI implementations for "generic" machine.
# A valid mpi target is either "mpich" or "openmpi-X.Y.Z", 
# where X, Y and Z are version numbers (major, minor and revision).
# Example:
# mpi_targets = ["mpich", "openmpi-2.1.6", "openmpi-3.1.4", "openmpi-4.0.2"]
mpi_targets = []

# Git repository of Yandasoft
git_repository = "https://github.com/ATNF/yandasoft.git"

# Docker image name is in this format: 
# target_prepend + (specific machine target OR mpi target for generic machine) + target_append
#image_prepend = "lahur/yandasoft-"
image_prepend = "lahur/yandasoft-"
image_append = ":latest"

# Set True if this is just a dry run. No Docker image will be created.
dry_run = True

# Name for sample batch files (leave empty if not needed)
# sample_batch = "pearcey"
sample_batch = ""

#------------------------------------------------------------------------------
# CODE

import sys
import argparse
import subprocess

# Sanitizing parameters

machine_targets = list(map(str.lower, machine_targets))
mpi_targets = list(map(str.lower, mpi_targets))


class DockerClass:
    def set_file_name(self, file_name):
        self.file_name = file_name

    def set_content(self, content):
        self.content = content

    def set_image(self, image):
        self.image = image

    def write(self):
        '''Write dockerfile'''
        f = open(self.file_name, "w")
        f.write(self.content)
        f.close()


def get_mpi_type_and_version(mpi_name):
    '''
    Given the full name of MPI, return the MPI type: mpich or openmpi
    as well as the version.
    '''
    if (len(mpi_name) > 5):
        if (mpi_name[0:5] == "mpich"):
            return ("mpich", mpi_name[6:])
        elif (mpi_name[0:8] == "openmpi-"):
            return ("openmpi", mpi_name[8:])
        else:
            raise ValueError("Illegal MPI name", mpi_name)
    elif (len(mpi_name) == 5):
        if (mpi_name == "mpich"):
            return("mpich", "")
        else:
            raise ValueError("Illegal MPI name", mpi_name)
    else:
        raise ValueError("Illegal MPI name", mpi_name)


def get_mpi_type(mpi_name):
    '''
    Given the full name of MPI implementation, return the type: 
    MPICH, OpenMPI or None
    '''
    if (mpi_name == "mpich"):
        return "mpich"
    elif (mpi_name[0:8] == "openmpi-"):
        return "openmpi"
    else:
        print("ERROR: Illegal MPI name: ", mpi_name)
        return None


def get_openmpi_version(mpi_name):
    '''
    Given the full name of MPI implementation, return OpenMPI version.
    Return None if not OpenMPI.
    '''
    if (mpi_name[0:8] == "openmpi-"):
        return mpi_name[8:]
    else:
        print("ERROR: This is not OpenMPI: ", mpi_name)
        return None


def main():
    '''
    The main code does 3 things:
    1) Create Dockerfiles for all MPI implementations.
    2) If required, create the corresponding Docker images.
    3) Create sample SLURM batch files.
    '''

    parser = argparse.ArgumentParser(description="Make Docker images for various MPI implementations")
    parser.add_argument('-i', '--image', help='Create Docker images', action='store_true')
    parser.add_argument('-s', '--slurm', help='Create sample batch files for SLURM', action='store_true')
    args = parser.parse_args()

    print("Making Dockerfiles for all targets ...")

    docker_targets = []

    header = ("# This file is automatically created by " + __file__ + "\n")

    common_bottom_part = (
    "WORKDIR /home/yandasoft\n"
    "RUN git pull " + git_repository + "\n"
    "RUN ./build_all.sh -a -O \"-DHAVE_MPI=1\"\n"
    "RUN ./build_all.sh -y -O \"-DHAVE_MPI=1\"\n"
    "RUN ./build_all.sh -e -O \"-DHAVE_MPI=1\"\n")

    for machine_target in machine_targets:
        if machine_target == "generic":
            for mpi_target in mpi_targets:
                (mpi_type, mpi_ver) = get_mpi_type_and_version(mpi_target)

                if (mpi_type == "mpich"):
                    if (mpi_ver == ""):
                        # if MPICH version is not specified, get the precompiled generic version
                        base_part = ("FROM csirocass/casabase-mpich:latest\n")
                        mpi_part = "RUN apt-get install -y mpich\n"

                    else:
                        # Otherwise, specific version of MPICH

                        base_part = ("FROM csirocass/casabase-mpich-" + mpi_ver + ":latest\n")
                        
                        # Download the source from MPICH website and build from source     
                        mpich_dir = "https://www.mpich.org/static/downloads/" + mpi_ver

                        # TODO: Check whether the version is correct and the file exists

                        mpi_part = (
                        "WORKDIR /home\n"
                        "RUN wget " + mpich_dir + "/" + mpi_target + ".tar.gz\n"
                        "RUN gunzip " + mpi_target + ".tar.gz\n"
                        "RUN tar -xf " + mpi_target + ".tar\n"
                        "WORKDIR /home/" + mpi_target + "\n"
                        "RUN ./configure --prefix=\"/home/$USER/mpich-install\n"
                        "RUN make\n"
                        "RUN make install\n"
                        "ENV PATH=$PATH:/home/$USER/mpich-install/bin\n"
                        "ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/home/$USER/mpich-install/lib/:/usr/local/lib\n")

                elif (mpi_type == "openmpi"):

                    base_part = ("FROM csirocass/casabase-openmpi-" + mpi_ver + ":latest\n")

                    # Download the source from OpenMPI website and build from source
                    openmpi_common_top_part = (
                    "WORKDIR /home\n")

                    openmpi_common_bottom_part = (
                    "RUN ./configure\n"
                    "RUN make all install\n"
                    "ENV LD_LIBRARY_PATH=/usr/local/lib\n")

                    openmpi_ver = mpi_target[8:]

                    # TODO: Check whether the version number is correct

                    # Directory name for OpenMPI download
                    openmpi_dir = "https://download.open-mpi.org/release/open-mpi/v" + openmpi_ver[0:3]

                    # TODO: Check whether this file exist

                    openmpi_version_part = (
                    "RUN wget " + openmpi_dir + "/" + mpi_target + ".tar.gz\n"
                    "RUN gunzip " + mpi_target + ".tar.gz\n"
                    "RUN tar -xf " + mpi_target + ".tar\n"
                    "WORKDIR /home/" + mpi_target + "\n")

                    mpi_part = openmpi_common_top_part + openmpi_version_part + openmpi_common_bottom_part

                else:
                    print("ERROR: unknown MPI target: ", mpi_target)
                    quit()

                docker_target = DockerClass()
                docker_target.set_file_name("Dockerfile-" + mpi_target)
                docker_target.set_content(header + base_part + mpi_part + common_bottom_part)
                docker_target.set_image(image_prepend + mpi_target + image_append)
                docker_targets.append(docker_target)
            # Next mpi target

        elif (machine_target == "galaxy"):
            base_part = ("FROM csirocass/casabase-galaxy:latest\n")

            docker_target = DockerClass()
            docker_target.set_file_name("Dockerfile-" + machine_target)
            docker_target.set_content(header + base_part + common_bottom_part)
            docker_target.set_image(image_prepend + machine_target + image_append)
            docker_targets.append(docker_target)

        else:
            print("ERROR: unknown machine target: ", machine_target)
            quit()

    print("Docker target count:", len(docker_targets))

    print()

    if args.image:
        print("Making Docker images for all targets ...")
    else:
        print("This is a dry run. No Docker image will be created")

    for docker_target in docker_targets:
        docker_target.write()
        docker_command = ("docker build -t " + docker_target.image + " -f " + docker_target.file_name + " .")
        if args.image:
            subprocess.run(docker_command, shell=True)
        else:
            subprocess.run("echo " + docker_command, shell=True)

    # Consider: Add automatic upload to DockerHub? This requires Docker login.

    if (sample_batch != ""):
        print()
        print("Making sample batch files ...")

        for mpi_target in mpi_targets:
            batch_common_part = (
            "#!/bin/bash -l\n"
            "## This file is automatically created by " + __file__ + "\n"
            "#SBATCH --ntasks=5\n"
            "##SBATCH --ntasks=305\n"
            "#SBATCH --time=02:00:00\n"
            "#SBATCH --job-name=cimager\n"
            "#SBATCH --export=NONE\n\n"
            "module load singularity/3.5.0\n")

            mpi_type = get_mpi_type(mpi_target)
            if (mpi_type == "mpich"):
                module = "mpich/3.3.0"
                image = "yandasoft-mpich_latest.sif"
                batch_mpi_part = (
                "module load " + module + "\n\n"
                "mpirun -n 5 singularity exec " + image +
                " cimager -c dirty.in > dirty_${SLURM_JOB_ID}.log\n")

            elif (mpi_type == "openmpi"):
                openmpi_ver = get_openmpi_version(mpi_target)
                if (openmpi_ver != None):
                    module = "openmpi/" + openmpi_ver + "-ofed45-gcc"
                    image = "yandasoft-" + openmpi_ver + "_latest.sif"
                    batch_mpi_part = (
                    "module load " + module + "\n\n"
                    "mpirun -n 5 -oversubscribe singularity exec " + image +
                    " cimager -c dirty.in > dirty_${SLURM_JOB_ID}.log\n")
                else:
                    break
            else:
                break

            batch_file = "sample-" + HPC + "-" + mpi_target + ".sbatch"
            print("Making batch file:", batch_file)
            f = open(batch_file, "w")
            f.write(batch_common_part + batch_mpi_part)
            f.close()


if (__name__ == "__main__"):
    if sys.version_info[0] == 3:
        main()
    else:
        raise ValueError("Must use Python 3")
