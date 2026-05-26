import { MigrationInterface, QueryRunner } from 'typeorm';

export class AddSubscriberTimestamps1779000000000
  implements MigrationInterface
{
  name = 'AddSubscriberTimestamps1779000000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "created_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" ADD "updated_at" TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`,
    );
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "updated_at"`,
    );
    await queryRunner.query(
      `ALTER TABLE "tracking_links_subscriber" DROP COLUMN "created_at"`,
    );
  }
}
